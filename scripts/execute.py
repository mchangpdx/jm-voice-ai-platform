"""
Phase-based execution harness for JM Voice AI Platform.
(JM Voice AI 플랫폼의 단계별 실행 하네스)
"""
import argparse
import subprocess
import sys
from typing import Callable

PHASES: dict[str, Callable[[], int]] = {}


def phase(name: str):
    def decorator(fn: Callable[[], int]):
        PHASES[name] = fn
        return fn
    return decorator


def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return result.returncode


@phase("lint")
def lint() -> int:
    print("[lint] Running ruff (backend) and eslint (frontend)...")
    rc = run(["ruff", "check", "backend/"])
    if rc != 0:
        return rc
    return run(["npx", "eslint", "frontend/src/", "--ext", ".ts,.tsx"])


@phase("type-check")
def type_check() -> int:
    print("[type-check] Running mypy and tsc...")
    rc = run(["mypy", "backend/app/"])
    if rc != 0:
        return rc
    return run(["npx", "tsc", "--noEmit", "--project", "frontend/tsconfig.json"])


@phase("test-unit")
def test_unit() -> int:
    print("[test-unit] Running pytest unit tests with coverage...")
    return run([
        "pytest", "backend/tests/unit/",
        "--cov=backend/app/skills/", "--cov-fail-under=85", "-v"
    ])


@phase("test-integration")
def test_integration() -> int:
    print("[test-integration] Running pytest integration tests...")
    return run(["pytest", "backend/tests/integration/", "-v"])


@phase("rls-audit")
def rls_audit() -> int:
    print("[rls-audit] Checking tenant_id presence in all models...")
    result = subprocess.run(
        ["grep", "-rL", "tenant_id", "backend/app/models/"],
        capture_output=True, text=True
    )
    if result.returncode == 2:  # grep error — directory missing or permission denied (grep 오류)
        print(f"[rls-audit] ERROR — grep failed: {result.stderr.strip()}")
        return 1
    missing = [f for f in result.stdout.strip().split("\n") if f and not f.endswith("__init__.py")]
    if missing:
        print(f"[rls-audit] FAIL — models missing tenant_id: {missing}")
        return 1
    print("[rls-audit] PASS — all models have tenant_id")
    return 0


@phase("relay-smoke")
def relay_smoke() -> int:
    print("[relay-smoke] Running relay pipeline smoke test...")
    return run(["pytest", "backend/tests/", "-k", "relay", "-v"])


@phase("build")
def build() -> int:
    print("[build] Building frontend with Vite...")
    return run(["npm", "run", "build", "--prefix", "frontend/"])


@phase("all")
def run_all() -> int:
    order = ["lint", "type-check", "test-unit", "test-integration", "rls-audit", "relay-smoke", "build"]
    for name in order:
        print(f"\n{'='*50}")
        rc = PHASES[name]()
        if rc != 0:
            print(f"\n[harness] FAILED at phase: {name}")
            return rc
    print("\n[harness] ALL PHASES PASSED")
    return 0


def main():
    parser = argparse.ArgumentParser(description="JM Voice AI Platform execution harness")
    parser.add_argument("--phase", choices=list(PHASES.keys()), default="all")
    args = parser.parse_args()
    sys.exit(PHASES[args.phase]())


if __name__ == "__main__":
    main()
