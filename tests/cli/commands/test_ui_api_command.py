# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import os
import subprocess
import sys
import time
from unittest import mock

import psutil
import pytest
from rich.console import Console

from airflow.cli.commands import ui_api_command
from tests.cli.commands._common_cli_classes import _CommonCLIGunicornTestClass

console = Console(width=400, color_system="standard")


@pytest.mark.db_test
class TestCliInternalAPI(_CommonCLIGunicornTestClass):
    main_process_regexp = r"airflow ui-api"

    @pytest.mark.execution_timeout(210)
    def test_cli_ui_api_background(self, tmp_path):
        parent_path = tmp_path / "gunicorn"
        parent_path.mkdir()
        pidfile_ui_api = parent_path / "pidflow-ui-api.pid"
        pidfile_monitor = parent_path / "pidflow-ui-api-monitor.pid"
        stdout = parent_path / "airflow-ui-api.out"
        stderr = parent_path / "airflow-ui-api.err"
        logfile = parent_path / "airflow-ui-api.log"
        try:
            # Run internal-api as daemon in background. Note that the wait method is not called.
            console.print("[magenta]Starting airflow ui-api --daemon")
            env = os.environ.copy()
            proc = subprocess.Popen(
                [
                    "airflow",
                    "ui-api",
                    "--daemon",
                    "--pid",
                    os.fspath(pidfile_ui_api),
                    "--stdout",
                    os.fspath(stdout),
                    "--stderr",
                    os.fspath(stderr),
                    "--log-file",
                    os.fspath(logfile),
                ],
                env=env,
            )
            assert proc.poll() is None

            pid_monitor = self._wait_pidfile(pidfile_monitor)
            console.print(f"[blue]Monitor started at {pid_monitor}")
            pid_ui_api = self._wait_pidfile(pidfile_ui_api)
            console.print(f"[blue]UI API started at {pid_ui_api}")
            console.print("[blue]Running airflow ui-api process:")
            # Assert that the ui-api and gunicorn processes are running (by name rather than pid).
            assert self._find_process(r"airflow ui-api --daemon", print_found_process=True)
            console.print("[blue]Waiting for gunicorn processes:")
            # wait for gunicorn to start
            for _ in range(30):
                if self._find_process(r"^gunicorn"):
                    break
                console.print("[blue]Waiting for gunicorn to start ...")
                time.sleep(1)
            console.print("[blue]Running gunicorn processes:")
            assert self._find_all_processes("^gunicorn", print_found_process=True)
            console.print("[magenta]ui-api process started successfully.")
            console.print(
                "[magenta]Terminating monitor process and expect "
                "ui-api and gunicorn processes to terminate as well"
            )
            proc = psutil.Process(pid_monitor)
            proc.terminate()
            assert proc.wait(120) in (0, None)
            self._check_processes(ignore_running=False)
            console.print("[magenta]All ui-api and gunicorn processes are terminated.")
        except Exception:
            console.print("[red]Exception occurred. Dumping all logs.")
            # Dump all logs
            for file in parent_path.glob("*"):
                console.print(f"Dumping {file} (size: {file.stat().st_size})")
                console.print(file.read_text())
            raise

    def test_cli_ui_api_debug(self, app):
        with mock.patch("subprocess.Popen") as Popen, mock.patch.object(ui_api_command, "GunicornMonitor"):
            port = "9092"
            hostname = "somehost"
            args = self.parser.parse_args(["ui-api", "--port", port, "--hostname", hostname, "--debug"])
            ui_api_command.ui_api(args)

            Popen.assert_called_with(
                [
                    "fastapi",
                    "dev",
                    "airflow/api_ui/main.py",
                    "--port",
                    port,
                    "--host",
                    hostname,
                ],
                close_fds=True,
            )

    def test_cli_ui_api_args(self):
        with mock.patch("subprocess.Popen") as Popen, mock.patch.object(ui_api_command, "GunicornMonitor"):
            args = self.parser.parse_args(
                [
                    "ui-api",
                    "--access-logformat",
                    "custom_log_format",
                    "--pid",
                    "/tmp/x.pid",
                ]
            )
            ui_api_command.ui_api(args)

            Popen.assert_called_with(
                [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "--workers",
                    "4",
                    "--worker-class",
                    "airflow.cli.commands.ui_api_command.AirflowUvicornWorker",
                    "--timeout",
                    "120",
                    "--bind",
                    "0.0.0.0:9091",
                    "--name",
                    "airflow-ui-api",
                    "--pid",
                    "/tmp/x.pid",
                    "--access-logfile",
                    "-",
                    "--error-logfile",
                    "-",
                    "--config",
                    "python:airflow.api_ui.gunicorn_config",
                    "--access-logformat",
                    "custom_log_format",
                    "airflow.api_ui.app:cached_app()",
                    "--preload",
                ],
                close_fds=True,
            )