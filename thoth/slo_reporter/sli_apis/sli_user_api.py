#!/usr/bin/env python3
# slo-reporter
# Copyright(C) 2020 Francesco Murdaca
#
# This program is free software: you can redistribute it and / or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""This file contains class for Thoth User-API."""

import logging
import os
import datetime

import numpy as np

import pandas as pd

from typing import Dict, List, Any

from thoth.slo_reporter.sli_base import SLIBase
from thoth.slo_reporter.sli_template import HTMLTemplates
from thoth.slo_reporter.configuration import Configuration
from thoth.slo_reporter.utils import retrieve_thoth_sli_from_ceph

from thoth.storages import CephStore

from io import StringIO


_LOGGER = logging.getLogger(__name__)

_USER_API_MEASUREMENT_UNIT = {
    "avg_percentage_successfull_request": {
        "name": "Successfull requests User-API (avg)",
        "measurement_unit": "%",
        "quantities": ["avg_total_request", "avg_successfull_request"],
    },
    "avg_up_time": {"name": "Uptime User-API (avg)", "measurement_unit": "%"},
}


class SLIUserAPI(SLIBase):
    """This class contains functions for User-API SLI."""

    _SLI_NAME = "user_api"

    sli_columns = [c for c in _USER_API_MEASUREMENT_UNIT]

    def __init__(self, configuration: Configuration):
        """Initialize SLI class."""
        self.configuration = configuration

        if self.configuration.dry_run:
            self.instance = "dry_run"
        else:
            self.instance = os.environ["PROMETHEUS_INSTANCE_USER_API"]

        self.total_columns = self.default_columns + self.sli_columns

    def _aggregate_info(self):
        """Aggregate info required for User-API SLI Report."""
        return {
            "query": self._query_sli(),
            "evaluation_method": self._evaluate_sli,
            "report_method": self._report_sli,
            "df_method": self._create_inputs_for_df_sli,
        }

    def _query_sli(self) -> List[str]:
        """Aggregate queries for User-API SLI Report."""
        query_labels = f'{{instance="{self.instance}"}}'
        query_labels_success = f'{{instance="{self.instance}", status=~"2.*"}}'
        query_labels_up = (
            f'{{instance="{self.instance}", job="Thoth User API Metrics ({self.configuration.environment})"}}'
        )

        return {
            "avg_total_request": {
                "query": f"sum(flask_http_request_total{query_labels})",
                "requires_range": True,
                "type": "average",
            },
            "avg_successfull_request": {
                "query": f"sum(flask_http_request_total{query_labels_success})",
                "requires_range": True,
                "type": "average",
            },
            "avg_up_time": f"avg_over_time(up{query_labels_up}[{self.configuration.interval}])",
        }

    def _evaluate_sli(self, sli: Dict[str, Any]) -> Dict[str, float]:
        """Evaluate SLI for report for User-API SLI.

        @param sli: It's a dict of SLI associated with the SLI type.
        """
        html_inputs = {}

        for user_api_quantity in _USER_API_MEASUREMENT_UNIT.keys():
            user_api_quantity_data = _USER_API_MEASUREMENT_UNIT[user_api_quantity]
            html_inputs[user_api_quantity] = {}

            if user_api_quantity == "avg_percentage_successfull_request":
                results = {}
                for quantity in user_api_quantity_data["quantities"]:
                    if sli[quantity] != "ErrorMetricRetrieval":
                        results[quantity] = sli[quantity]
                    else:
                        results[quantity] = np.nan

                if all(single_quantity != np.nan for single_quantity in results.values()):
                    if results["avg_total_request"] > 0:
                        percentage = results["avg_successfull_request"] / results["avg_total_request"]
                    else:
                        percentage = 0

                    html_inputs[user_api_quantity]["value"] = abs(round(percentage * 100, 3))
                else:
                    html_inputs[user_api_quantity]["value"] = np.nan

            else:
                if sli[user_api_quantity] != "ErrorMetricRetrieval":
                    html_inputs[user_api_quantity]["value"] = abs(round(sli[user_api_quantity] * 100, 3))
                else:
                    html_inputs[user_api_quantity]["value"] = np.nan

            html_inputs[user_api_quantity]["name"] = user_api_quantity_data["name"]
            html_inputs[user_api_quantity]["measurement_unit"] = user_api_quantity_data["measurement_unit"]

        return html_inputs

    def _report_sli(self, sli: Dict[str, Any], ceph_sli: CephStore) -> str:
        """Create report for User-API SLI.

        @param sli: It's a dict of SLI associated with the SLI type.
        """
        html_inputs = self._evaluate_sli(sli=sli)
        sli_path = f"{self._SLI_NAME}/{self._SLI_NAME}-{self.configuration.last_week_time}.csv"
        retrieved_data = retrieve_thoth_sli_from_ceph(ceph_sli, sli_path)
        data = StringIO(retrieved_data)
        last_week_data = pd.read_csv(data, names=self.total_columns)

        for c in self.sli_columns:
            diff = (html_inputs[c]["value"] - last_week_data[c])[0].item()
            if diff > 0:
                html_inputs[c]["change"] = "+{:.3f}".format(diff)
            elif diff < 0:
                html_inputs[c]["change"] = "-{:.3f}".format(diff)
            else:
                html_inputs[c]["change"] = diff

        report = HTMLTemplates.thoth_user_api_template(html_inputs=html_inputs)
        return report

    def _create_inputs_for_df_sli(
        self, sli: Dict[str, Any], datetime: datetime.datetime, timestamp: datetime.datetime,
    ) -> Dict[str, Any]:
        """Create inputs for SLI dataframe to be stored.

        @param sli: It's a dict of SLI associated with the SLI type.
        """
        parameters = locals()
        parameters.pop("self")

        output = self._create_default_inputs_for_df_sli(**parameters)

        return output
