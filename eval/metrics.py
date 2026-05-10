"""
Evaluation metrics for MACOG iac-eval harness.

  compute_bleu    — corpus-level BLEU (sacrebleu)
  run_rego_eval   — OPA eval on terraform plan JSON (iac-eval two-stage methodology)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from agents._rtk import wrap_cmd


def compute_bleu(generated: str, reference: str) -> float:
    """
    BLEU score normalised to [0, 1].
    Returns 0.0 if either string is empty.
    """
    if not generated or not reference:
        return 0.0
    try:
        import sacrebleu  # type: ignore[import]
        result = sacrebleu.corpus_bleu([generated], [[reference]])
        return result.score / 100.0
    except Exception:
        return 0.0


def compute_codebert_score(generated: str, reference: str) -> float | None:
    """
    CodeBERTScore-style semantic similarity in [0, 1].

    This is optional because it requires the bert-score package and a local or
    downloadable microsoft/codebert-base model. Returning None keeps smoke tests
    lightweight while preserving the paper-style metric column when available.
    """
    if not generated or not reference:
        return None
    try:
        from bert_score import score  # type: ignore[import]

        _, _, f1 = score(
            [generated],
            [reference],
            model_type="microsoft/codebert-base",
            lang="en",
            verbose=False,
            rescale_with_baseline=False,
        )
        return float(f1[0])
    except Exception:
        return None


def _rego_package(rego_policy: str) -> str:
    match = re.search(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)\s*$", rego_policy)
    return match.group(1) if match else "terraform.validation"


def _opa_value(stdout: str) -> object:
    data = json.loads(stdout)
    return data["result"][0]["expressions"][0]["value"]


def _query_candidates(rego_policy: str) -> list[str]:
    package = _rego_package(rego_policy)
    base = "data." + package

    rules = [
        "is_configuration_valid",
        "has_valid_resources",
        "allow",
        "valid",
        "is_valid",
        "is_valid_configuration",
    ]
    rules.extend(
        rule
        for rule in re.findall(r"(?m)^\s*default\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", rego_policy)
        if rule not in rules
    )
    candidates = [f"{base}.{rule}" for rule in rules if re.search(rf"(?m)^\s*(default\s+)?{rule}\b", rego_policy)]
    candidates.extend(
        f"{base}.{rule}"
        for rule in rules
        if f"{base}.{rule}" not in candidates
    )
    candidates.append("data")
    return candidates


def _passes_from_value(value: object) -> tuple[bool | None, list[str]]:
    if isinstance(value, bool):
        return value, [] if value else ["validation rule returned false"]
    if isinstance(value, list):
        return len(value) == 0, [str(v) for v in value]
    if isinstance(value, dict):
        for key in ("is_configuration_valid", "has_valid_resources", "allow", "valid", "is_valid", "is_valid_configuration"):
            if isinstance(value.get(key), bool):
                passed = bool(value[key])
                return passed, [] if passed else [f"{key} returned false"]
        if "deny" in value:
            deny = value["deny"]
            violations = [str(v) for v in deny] if isinstance(deny, list) else [str(deny)]
            return len(violations) == 0, violations
        if "violations" in value:
            violations = value["violations"]
            violations = [str(v) for v in violations] if isinstance(violations, list) else [str(violations)]
            return len(violations) == 0, violations
    return None, []


def _opa_bin() -> str:
    return os.environ.get("OPA_BIN") or shutil.which("opa") or ("/private/tmp/opa" if os.path.exists("/private/tmp/opa") else "opa")


def _matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for idx in range(open_index, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    return len(text)


def _parse_hcl_value(raw: str) -> tuple[object, list[str]]:
    value = raw.strip().rstrip(",")
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1], []
    if value in {"true", "false"}:
        return value == "true", []
    if re.fullmatch(r"-?\d+", value):
        return int(value), []
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value), []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return [], []
        items = [item.strip() for item in inner.split(",")]
        parsed = [_parse_hcl_value(item)[0] for item in items]
        refs = [str(item) for item in parsed if re.fullmatch(r"[A-Za-z_][\w]*\.[A-Za-z_][\w-]*\.[A-Za-z_][\w]*", str(item))]
        return parsed, refs
    refs = re.findall(r"\b[A-Za-z_][\w]*\.[A-Za-z_][\w-]*\.[A-Za-z_][\w]*\b", value)
    return value, refs


def _synthetic_plan_from_hcl(hcl: str) -> dict:
    resources = []
    for match in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', hcl):
        rtype, name = match.group(1), match.group(2)
        end = _matching_brace(hcl, match.end() - 1)
        body = hcl[match.end():end]
        expressions = {}
        values = {}
        for line in body.splitlines():
            attr = re.match(r"^\s*([A-Za-z_][\w-]*)\s*=\s*(.+?)\s*$", line)
            if not attr:
                continue
            key, raw_value = attr.group(1), attr.group(2)
            value, refs = _parse_hcl_value(raw_value)
            expr: dict[str, object] = {"constant_value": value}
            if refs:
                expr["references"] = refs
            expressions[key] = expr
            values[key] = value
        resources.append({
            "type": rtype,
            "name": name,
            "expressions": expressions,
            "values": values,
        })
    return {
        "configuration": {"root_module": {"resources": resources}},
        "planned_values": {"root_module": {"resources": resources}},
        "resource_changes": [
            {"type": r["type"], "name": r["name"], "change": {"after": r["values"]}}
            for r in resources
        ],
    }


def _write_synthetic_plan(sdir: Path, plan_json_path: Path) -> bool:
    hcl = "\n".join(path.read_text() for path in sorted(sdir.glob("*.tf")))
    if not hcl.strip():
        return False
    plan_json_path.write_text(json.dumps(_synthetic_plan_from_hcl(hcl), indent=2))
    return True


def run_rego_eval(rego_policy: str, session_dir: str) -> dict:
    """
    Run iac-eval Stage 2: OPA eval on terraform plan JSON.

    Flow (mirrors iac-eval/evaluation/eval.py):
      1. Write rego_policy to {session_dir}/policy/iac_eval.rego
      2. terraform init && terraform plan -out=tfplan
      3. terraform show -json tfplan  →  plan.json
      4. Detect Rego v1 (import rego.v1) → add --v1-compatible flag
      5. opa eval [-v1-compatible] -i plan.json -d policy.rego <validity rule>
      6. Parse the explicit boolean validity rule used by iac-eval policies.

    Returns:
        {
            "passed":     bool | None,   # None when terraform/opa unavailable
            "violations": list[str],
            "error":      str | None,
        }
    """
    sdir = Path(session_dir)
    policy_dir = sdir / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)
    policy_file = policy_dir / "iac_eval.rego"
    policy_file.write_text(rego_policy)

    tf_files = list(sdir.glob("*.tf"))
    if not tf_files:
        return {"passed": None, "violations": [], "error": "no .tf files in session_dir"}

    tf_env = {
        **os.environ,
        "TF_INPUT": "0",
        "TF_CLI_ARGS_init": "-no-color",
        "TF_CLI_ARGS_plan": "-no-color",
    }

    plan_json_path = sdir / "plan.json"

    # Steps 2-3: terraform init + plan + show
    used_synthetic_plan = False
    try:
        for cmd in [
            wrap_cmd(["terraform", "init", "-no-color"]),
            wrap_cmd(["terraform", "plan", "-refresh=false", "-out=tfplan", "-no-color"]),
            wrap_cmd(["terraform", "show", "-json", "tfplan"]),
        ]:
            result = subprocess.run(
                cmd, cwd=str(sdir), capture_output=True,
                text=True, timeout=120, env=tf_env,
            )
            action = "show" if "show" in cmd else "plan" if "plan" in cmd else "init"
            if action == "show":
                if result.returncode == 0:
                    plan_json_path.write_text(result.stdout)
            elif result.returncode != 0:
                if _write_synthetic_plan(sdir, plan_json_path):
                    used_synthetic_plan = True
                    break
                return {
                    "passed": None, "violations": [],
                    "error": f"terraform {action} failed: {result.stderr[:300]}",
                }
    except FileNotFoundError:
        if not _write_synthetic_plan(sdir, plan_json_path):
            return {"passed": None, "violations": [], "error": "terraform not installed"}
        used_synthetic_plan = True
    except subprocess.TimeoutExpired:
        if not _write_synthetic_plan(sdir, plan_json_path):
            return {"passed": None, "violations": [], "error": "terraform timeout"}
        used_synthetic_plan = True

    if not plan_json_path.exists():
        return {"passed": None, "violations": [], "error": "plan.json not generated"}

    # Steps 4-5: OPA eval
    is_rego_v1 = "import rego.v1" in rego_policy
    errors: list[str] = []
    for query in _query_candidates(rego_policy):
        opa_cmd = [_opa_bin(), "eval"]
        if is_rego_v1:
            opa_cmd.append("--v1-compatible")
        else:
            opa_cmd.append("--v0-compatible")
        opa_cmd += ["-i", str(plan_json_path), "-d", str(policy_file), query]

        try:
            opa_proc = subprocess.run(opa_cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            return {"passed": None, "violations": [], "error": "opa not installed"}
        except subprocess.TimeoutExpired:
            return {"passed": None, "violations": [], "error": "opa timeout"}

        if opa_proc.returncode != 0:
            errors.append(f"{query}: {opa_proc.stderr[:200]}")
            continue

        try:
            passed, violations = _passes_from_value(_opa_value(opa_proc.stdout))
        except (KeyError, IndexError, json.JSONDecodeError, TypeError):
            errors.append(f"{query}: unparsable OPA output")
            continue
        if passed is not None:
            return {
                "passed": passed,
                "violations": violations,
                "error": None,
                "query": query,
                "plan_source": "synthetic_hcl" if used_synthetic_plan else "terraform_plan",
            }

    return {
        "passed": None,
        "violations": [],
        "error": "no boolean OPA validity rule found" + (f": {errors[-1]}" if errors else ""),
    }
