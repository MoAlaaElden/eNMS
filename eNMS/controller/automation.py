from apscheduler.jobstores.base import JobLookupError
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from flask import request, session
from itertools import chain
from napalm._SUPPORTED_DRIVERS import SUPPORTED_DRIVERS
from netmiko.ssh_dispatcher import CLASS_MAPPER, FILE_TRANSFER_MAP
from operator import attrgetter
from pathlib import Path
from re import search, sub
from subprocess import PIPE, Popen
from typing import Any, Dict, Optional

from eNMS.concurrency import run_job
from eNMS.controller.base import BaseController
from eNMS.database import Session
from eNMS.database.functions import delete, factory, fetch, fetch_all, objectify


class AutomationController(BaseController):

    NETMIKO_DRIVERS = sorted((driver, driver) for driver in CLASS_MAPPER)
    NETMIKO_SCP_DRIVERS = sorted((driver, driver) for driver in FILE_TRANSFER_MAP)
    NAPALM_DRIVERS = sorted((driver, driver) for driver in SUPPORTED_DRIVERS[1:])
    connections_cache: dict = {
        "napalm": defaultdict(dict),
        "netmiko": defaultdict(dict),
    }
    job_db: dict = defaultdict(dict)
    run_logs: dict = defaultdict(list)

    def add_edge(
        self, workflow_id: int, subtype: str, source: int, destination: int
    ) -> dict:
        workflow_edge = factory(
            "WorkflowEdge",
            **{
                "name": f"{workflow_id}-{subtype}:{source}->{destination}",
                "workflow": workflow_id,
                "subtype": subtype,
                "source": source,
                "destination": destination,
            },
        )
        Session.commit()
        now = self.get_time()
        fetch("Workflow", id=workflow_id).last_modified = now
        return {"edge": workflow_edge.serialized, "update_time": now}

    def add_jobs_to_workflow(self, workflow_id: int, job_ids: str) -> Dict[str, Any]:
        workflow = fetch("Workflow", id=workflow_id)
        jobs = objectify("Job", [int(job_id) for job_id in job_ids.split("-")])
        for job in jobs:
            job.workflows.append(workflow)
        now = self.get_time()
        workflow.last_modified = now
        return {"jobs": [job.serialized for job in jobs], "update_time": now}

    def clear_results(self, job_id: int) -> None:
        for result in fetch("Result", all_matches=True, allow_none=True, job_id=job_id):
            Session.delete(result)

    def delete_edge(self, workflow_id: int, edge_id: int) -> str:
        delete("WorkflowEdge", id=edge_id)
        now = self.get_time()
        fetch("Workflow", id=workflow_id).last_modified = now
        return now

    def delete_node(self, workflow_id: int, job_id: int) -> dict:
        workflow, job = fetch("Workflow", id=workflow_id), fetch("Job", id=job_id)
        workflow.jobs.remove(job)
        now = self.get_time()
        workflow.last_modified = now
        return {"job": job.serialized, "update_time": now}

    def duplicate_workflow(self, workflow_id: int, **kwargs: Any) -> dict:
        parent_workflow = fetch("Workflow", id=workflow_id)
        new_workflow = factory("Workflow", **kwargs)
        Session.commit()
        for job in parent_workflow.jobs:
            new_workflow.jobs.append(job)
            job.positions[new_workflow.name] = job.positions[parent_workflow.name]
        Session.commit()
        for edge in parent_workflow.edges:
            subtype, src, destination = edge.subtype, edge.source, edge.destination
            new_workflow.edges.append(
                factory(
                    "WorkflowEdge",
                    **{
                        "name": (
                            f"{new_workflow.id}-{subtype}:"
                            f"{src.id}->{destination.id}"
                        ),
                        "workflow": new_workflow.id,
                        "subtype": subtype,
                        "source": src.id,
                        "destination": destination.id,
                    },
                )
            )
        return new_workflow.serialized

    def get_job_logs(self, runtime: str) -> list:
        return "\n".join(self.run_logs[runtime])

    def get_runtimes(self, type: str, id: int) -> list:
        if type == "device":
            results = fetch("Result", allow_none=True, all_matches=True, device_id=id)
            runs = [result.run for result in results]
        else:
            runs = fetch("Run", allow_none=True, all_matches=True, job_id=id)
        return sorted(set((run.runtime, run.runtime) for run in runs))

    def get_device_list(self, id: int, **kw: Any) -> list:
        comp = "_compare" if kw["compare"] else ""
        defaults = [
            ("global", "Entire runtime payload"),
            ("all", "All devices"),
            ("all failed", "All devices that failed"),
            ("all passed", "All devices that passed"),
        ]
        runtime_key = "parent_runtime" if "job" in kw else "runtime"
        request = {runtime_key: kw.get(f"runtime{comp}")}
        if kw.get(f"job{comp}") not in ("global", "all"):
            request["job_id"] = kw.get(f"job{comp}", id)
        runs = fetch("Run", allow_none=True, **request)
        if not runs:
            return defaults
        return defaults + list(
            set(
                (result.device_id, result.device_name)
                for result in runs.results
                if result.device_id
            )
        )

    def get_job_list(self, results_type: str, id: int, **kw: Any) -> list:
        comp = "_compare" if kw["compare"] else ""
        defaults = [
            ("global", "Entire runtime payload"),
            ("all", "All jobs"),
            ("all failed", "All jobs that failed"),
            ("all passed", "All jobs that passed"),
        ]
        return defaults + list(
            dict.fromkeys(
                (run.job_id, run.job.name)
                for run in sorted(
                    fetch(
                        "Run",
                        parent_runtime=kw.get(f"runtime{comp}"),
                        allow_none=True,
                        all_matches=True,
                    ),
                    key=attrgetter("runtime"),
                )
                if result.job_id
            )
        )

    def get_results(self, type: str, id: int, **kw) -> Optional[dict]:
        comp = "_compare" if kw["compare"] else ""
        return getattr(self, f"get_{type}_results")(
            id,
            **{
                "runtime": kw.get(f"runtime{comp}"),
                "device": kw.get(f"device{comp}"),
                "job": kw.get(f"job{comp}"),
            },
        )

    def get_workflow_results(self, id: int, runtime, device, job) -> Optional[dict]:
        request = {"parent_runtime": runtime}

    def get_service_results(self, id: int, runtime, device, **_) -> Optional[dict]:
        request = {"runtime": runtime}
        if "all" in device:
            request["all_matches"] = True
            if device != "all":
                request["success"] = device == "all passed"
        runs = fetch("Run", allow_none=True, **request)
        if isinstance(runs, list):
            runs.sort(key=attrgetter("runtime"))
        else:
            runs = [runs]
        results = list(chain.from_iterable(run.results for run in runs))
        if "all" not in device:
            device_id = None if device == "global" else int(device)
            results = [r for r in results if device_id == r.device_id]
            return results[0].result
        else:
            return {r.device_name: r.result for r in results if r.device_id}

    def compare_job_results(self, id: int, **kwargs: Any) -> dict:
        kwargs.pop("compare")
        first = self.str_dict(
            self.str_dict(self.get_job_results(id, compare=False, **kwargs))
        ).splitlines()
        second = self.str_dict(
            self.get_job_results(id, compare=True, **kwargs)
        ).splitlines()
        opcodes = SequenceMatcher(None, first, second).get_opcodes()
        return {"first": first, "second": second, "opcodes": opcodes}

    def reset_status(self) -> None:
        for job in fetch_all("Job"):
            job.status = "Idle"

    def restart_workflow(self, workflow_id: int, **kwargs: Any) -> dict:
        workflow = fetch("Workflow", id=workflow_id)
        result = fetch(
            "Result",
            allow_none=True,
            job_id=workflow_id,
            runtime=kwargs.get("payload_version"),
        )
        payload = result.result["results"] if result else {}
        payload_jobs = set(payload) & set(kwargs["payloads_to_include"])
        payload = {k: payload[k] for k in payload if k in payload_jobs}
        if workflow.status == "Running":
            return {"error": "Workflow is already running."}
        self.scheduler.add_job(
            id=self.get_time(),
            func=run_job,
            run_date=datetime.now(),
            args=[workflow_id, None, None, payload, kwargs["start_points"]],
            trigger="date",
        )
        return workflow.name

    def run_job(self, job_id: int, asynchronous: bool = True) -> dict:
        job = fetch("Job", id=job_id)
        if job.status == "Running":
            return {"error": f"{job.type} is already running."}
        runtime = self.get_time()
        if asynchronous:
            self.scheduler.add_job(
                id=self.get_time(),
                func=run_job,
                run_date=datetime.now(),
                args=[job.id, None, None, None, None, runtime],
                trigger="date",
            )
        else:
            job.run(runtime=runtime)
        return {**job.serialized, "runtime": runtime}

    def save_positions(self, workflow_id: int) -> str:
        now = self.get_time()
        workflow = fetch("Workflow", allow_none=True, id=workflow_id)
        workflow.last_modified = now
        session["workflow"] = workflow.id
        for job_id, position in request.json.items():
            job = fetch("Job", id=job_id)
            job.positions[workflow.name] = (position["x"], position["y"])
        return now

    def calendar_init(self) -> dict:
        tasks = {}
        for task in fetch_all("Task"):
            # javascript dates range from 0 to 11, we must account for that by
            # substracting 1 to the month for the date to be properly displayed in
            # the calendar
            date = task.next_run_time
            if not date:
                continue
            python_month = search(r".*-(\d{2})-.*", date).group(1)  # type: ignore
            month = "{:02}".format((int(python_month) - 1) % 12)
            js_date = [
                int(i)
                for i in sub(
                    r"(\d+)-(\d+)-(\d+) (\d+):(\d+).*",
                    r"\1," + month + r",\3,\4,\5",
                    date,
                ).split(",")
            ]
            tasks[task.name] = {**task.serialized, **{"date": js_date}}
        return tasks

    def scheduler_action(self, action: str) -> None:
        getattr(self.scheduler, action)()

    def task_action(self, action: str, task_id: int) -> Optional[dict]:
        try:
            return getattr(fetch("Task", id=task_id), action)()
        except JobLookupError:
            return {"error": "This task no longer exists."}

    def scan_playbook_folder(self) -> list:
        path = Path(self.playbook_path or self.path / "playbooks")
        playbooks = [[str(f) for f in path.glob(e)] for e in ("*.yaml", "*.yml")]
        return sorted(sum(playbooks, []))
