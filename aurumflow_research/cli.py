"""Command-line entry point for catalog inspection and isolated research runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import (
    ConfigurationError,
    load_config,
    parse_parameter_overrides,
)
from .data import DataCatalog, DataSourceError
from .discovery import DiscoveryError, ExperimentCatalog, ResearchObjectCatalog
from .runner import ExperimentRunFailed, ExperimentRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aurumflow-research",
        description="Run isolated, manifest-defined scientific research experiments.",
    )
    parser.add_argument("--config", type=Path, help="Path to central research TOML")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_objects = subparsers.add_parser("list-objects", help="List research objects")
    list_objects.add_argument("--json", action="store_true", dest="as_json")

    list_experiments = subparsers.add_parser(
        "list-experiments", help="List discoverable experiments"
    )
    list_experiments.add_argument("--json", action="store_true", dest="as_json")

    run = subparsers.add_parser("run", help="Run one experiment by manifest ID")
    run.add_argument("experiment_id")
    run.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override an experiment parameter; VALUE accepts JSON syntax",
    )
    return parser


def _catalogs(config):
    objects = ResearchObjectCatalog.discover(config.paths.research_objects)
    experiments = ExperimentCatalog.discover(config.paths.research_objects, objects)
    return objects, experiments


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        objects, experiments = _catalogs(config)
        if args.command == "list-objects":
            payload = [
                {
                    "id": item.object_id,
                    "title": item.title,
                    "layer": item.layer,
                    "lifecycle": item.lifecycle.value,
                    "decision": item.decision.value,
                }
                for item in objects
            ]
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item['id']}: {item['title']} "
                        f"[{item['lifecycle']}/{item['decision']}]"
                    )
            return 0

        if args.command == "list-experiments":
            payload = [
                {
                    "id": item.experiment_id,
                    "research_object": item.research_object,
                    "title": item.title,
                    "version": item.version,
                }
                for item in experiments
            ]
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item['id']}: {item['title']} "
                        f"({item['research_object']}, v{item['version']})"
                    )
            return 0

        definition = experiments.get(args.experiment_id)
        overrides = parse_parameter_overrides(args.param)
        data_catalog = DataCatalog.from_config(
            project_root=config.project.root,
            definitions=config.data_sources,
        )
        entry_point = experiments.load_entry_point(definition)
        outcome = ExperimentRunner(config, data_catalog).run(
            definition, entry_point, overrides
        )
        print(
            json.dumps(
                {
                    "run_id": outcome.run_id,
                    "research_status": outcome.result.research_status.value,
                    "output_location": str(outcome.output_dir),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except ExperimentRunFailed as exc:
        print(
            json.dumps(
                {"error": str(exc), "output_location": str(exc.output_dir)},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except (ConfigurationError, DataSourceError, DiscoveryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
