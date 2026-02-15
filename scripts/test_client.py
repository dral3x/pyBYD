#!/usr/bin/env python3
"""Live BYD client verification tool for shared-account payload parity.

This script performs a minimal end-to-end session using pyBYD and reports
whether outgoing request envelopes and incoming responses are comparable to
captured app behavior.

Credential sourcing (shared-account first):
- BYD_SHARED_USERNAME (fallback: BYD_USERNAME)
- BYD_SHARED_PASSWORD (fallback: BYD_PASSWORD)
- BYD_SHARED_CONTROL_PIN (fallback: BYD_CONTROL_PIN)

Default behavior:
1) login/session bootstrap,
2) get_vehicles,
3) verify_control_password on first VIN,
4) print comparability report for captured traces.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))


def _maybe_reexec_with_project_venv() -> None:
    candidate_env = (_repo / ".venv").resolve()
    candidate_python = candidate_env / "bin" / "python"
    if not candidate_python.exists():
        return

    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == candidate_env:
        return
    if os.environ.get("PYBYD_TEST_CLIENT_REEXEC") == "1":
        return

    env = dict(os.environ)
    env["PYBYD_TEST_CLIENT_REEXEC"] = "1"
    os.execve(str(candidate_python), [str(candidate_python), *sys.argv], env)


_maybe_reexec_with_project_venv()

from pybyd import BydApiError, BydClient, BydConfig  # noqa: E402
from pybyd._crypto.aes import aes_decrypt_utf8  # noqa: E402
from pybyd._crypto.hashing import pwd_login_key  # noqa: E402


def _install_transport_trace(client: BydClient, traces: list[dict[str, Any]]) -> None:
    """Install a best-effort transport trace recorder onto an initialized client.

    The library no longer exposes a first-class trace callback; for script
    parity checks we wrap the underlying transport's `post_secure`.
    """

    transport = getattr(client, "_transport", None)
    if transport is None:
        raise RuntimeError("Client transport not initialized; use within 'async with BydClient(...)'")

    original_post_secure = transport.post_secure
    codec = getattr(transport, "_codec", None)

    async def traced_post_secure(endpoint: str, outer_payload: Mapping[str, Any]) -> dict[str, Any]:
        outer_dict = dict(outer_payload)
        encoded: str | None = None
        if codec is not None:
            try:
                encoded = codec.encode_envelope(json.dumps(outer_dict, separators=(",", ":")))
            except Exception:
                encoded = None

        trace: dict[str, Any] = {
            "endpoint": endpoint,
            "request": {
                "outer": outer_dict,
                "encoded": encoded,
            },
            "http": {
                "url": f"{client._config.base_url}{endpoint}",
            },
        }
        try:
            decoded = await original_post_secure(endpoint, outer_payload)
            trace["response"] = {"decoded": decoded}
            return decoded
        except Exception as exc:
            trace["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            traces.append(trace)

    transport.post_secure = traced_post_secure

COMMON_OUTER_KEYS: tuple[str, ...] = (
    "countryCode",
    "encryData",
    "identifier",
    "imeiMD5",
    "language",
    "reqTimestamp",
    "sign",
    "ostype",
    "imei",
    "mac",
    "model",
    "sdk",
    "mod",
    "serviceTime",
    "checkcode",
)

VERIFY_INNER_KEYS: tuple[str, ...] = (
    "commandPwd",
    "deviceType",
    "functionType",
    "imeiMD5",
    "networkType",
    "random",
    "timeStamp",
    "version",
    "vin",
)


@dataclass(frozen=True)
class CompareResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class LayerDecryptResult:
    key_name: str
    plaintext: str
    parsed: Any


def _is_upper_hex(text: str, expected_len: int) -> bool:
    return len(text) == expected_len and all(ch in "0123456789ABCDEF" for ch in text)


def _load_shared_config() -> BydConfig:
    username = os.environ.get("BYD_SHARED_USERNAME") or os.environ.get("BYD_USERNAME")
    password = os.environ.get("BYD_SHARED_PASSWORD") or os.environ.get("BYD_PASSWORD")
    control_pin = os.environ.get("BYD_SHARED_CONTROL_PIN") or os.environ.get("BYD_CONTROL_PIN")

    missing: list[str] = []
    if not username:
        missing.append("BYD_SHARED_USERNAME or BYD_USERNAME")
    if not password:
        missing.append("BYD_SHARED_PASSWORD or BYD_PASSWORD")
    if not control_pin:
        missing.append("BYD_SHARED_CONTROL_PIN or BYD_CONTROL_PIN")

    if missing:
        raise SystemExit("Missing required env vars: " + ", ".join(missing))

    # Keep control_pin unset on the client config so automatic startup
    # preflight in get_vehicles is not triggered. We call verify explicitly
    # with the shared PIN to keep this script deterministic.
    return BydConfig.from_env(
        username=username,
        password=password,
        control_pin=None,
    )


def _load_shared_control_pin() -> str:
    control_pin = os.environ.get("BYD_SHARED_CONTROL_PIN") or os.environ.get("BYD_CONTROL_PIN")
    if not control_pin:
        raise SystemExit("Missing required env var: BYD_SHARED_CONTROL_PIN or BYD_CONTROL_PIN")
    return control_pin


def _find_latest_trace(traces: list[dict[str, Any]], endpoint: str) -> dict[str, Any] | None:
    for trace in reversed(traces):
        if trace.get("endpoint") == endpoint:
            return trace
    return None


def _best_effort_decrypt(ciphertext: str, keys: list[tuple[str, str]]) -> LayerDecryptResult | None:
    for key_name, key_value in keys:
        if not key_value:
            continue
        try:
            plaintext = aes_decrypt_utf8(ciphertext, key_value)
        except Exception:
            continue
        try:
            parsed = json.loads(plaintext)
        except Exception:
            parsed = None
        return LayerDecryptResult(
            key_name=key_name,
            plaintext=plaintext,
            parsed=parsed,
        )
    return None


def _build_layered_trace_dump(
    traces: list[dict[str, Any]],
    *,
    session_content_key: str,
    login_key: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    key_candidates = [
        ("session.content_key", session_content_key),
        ("login.pwd_login_key", login_key),
    ]

    for index, trace in enumerate(traces, start=1):
        endpoint = str(trace.get("endpoint", ""))
        request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
        response = trace.get("response") if isinstance(trace.get("response"), dict) else {}
        outer_req = request.get("outer") if isinstance(request.get("outer"), dict) else None
        decoded_rsp = response.get("decoded") if isinstance(response.get("decoded"), dict) else None

        req_decrypt: dict[str, Any] | None = None
        if isinstance(outer_req, dict):
            encry_data = outer_req.get("encryData")
            if isinstance(encry_data, str) and encry_data:
                decrypted = _best_effort_decrypt(encry_data, key_candidates)
                if decrypted is None:
                    req_decrypt = {
                        "status": "failed",
                        "reason": "unable to decrypt with known keys",
                    }
                else:
                    req_decrypt = {
                        "status": "ok",
                        "key": decrypted.key_name,
                        "plaintext": decrypted.plaintext,
                        "json": decrypted.parsed,
                    }

        rsp_decrypt: dict[str, Any] | None = None
        if isinstance(decoded_rsp, dict):
            respond_data = decoded_rsp.get("respondData")
            if isinstance(respond_data, str) and respond_data:
                decrypted = _best_effort_decrypt(respond_data, key_candidates)
                if decrypted is None:
                    rsp_decrypt = {
                        "status": "failed",
                        "reason": "unable to decrypt with known keys",
                    }
                else:
                    rsp_decrypt = {
                        "status": "ok",
                        "key": decrypted.key_name,
                        "plaintext": decrypted.plaintext,
                        "json": decrypted.parsed,
                    }
            elif respond_data in ("", None):
                rsp_decrypt = {
                    "status": "empty",
                    "reason": "respondData is empty or missing",
                }

        output.append(
            {
                "index": index,
                "endpoint": endpoint,
                "layers": {
                    "request": {
                        "outer": outer_req,
                        "bangcle_encoded": request.get("encoded"),
                        "decrypted_inner": req_decrypt,
                    },
                    "transport": {
                        "http": trace.get("http"),
                    },
                    "response": {
                        "http_outer": response.get("outer"),
                        "decoded": decoded_rsp,
                        "decrypted_respondData": rsp_decrypt,
                    },
                },
            }
        )

    return output


def _compare_common_outer(outer: dict[str, Any]) -> list[CompareResult]:
    results: list[CompareResult] = []
    missing = [key for key in COMMON_OUTER_KEYS if key not in outer]
    results.append(
        CompareResult(
            name="outer.required_keys",
            ok=not missing,
            detail="missing=" + (", ".join(missing) if missing else "none"),
        )
    )

    req_ts = str(outer.get("reqTimestamp", ""))
    svc_ts = str(outer.get("serviceTime", ""))
    time_ok = req_ts.isdigit() and svc_ts.isdigit() and len(req_ts) >= 13 and len(svc_ts) >= 13
    results.append(
        CompareResult(
            name="outer.timestamps",
            ok=time_ok,
            detail=f"reqTimestamp={req_ts} serviceTime={svc_ts}",
        )
    )

    sign = str(outer.get("sign", ""))
    sign_ok = 1 <= len(sign) <= 40 and all(ch in "0123456789abcdefABCDEF" for ch in sign)
    results.append(
        CompareResult(
            name="outer.sign_shape",
            ok=sign_ok,
            detail=f"len={len(sign)}",
        )
    )

    checkcode = str(outer.get("checkcode", ""))
    check_ok = len(checkcode) == 32 and all(ch in "0123456789abcdef" for ch in checkcode)
    results.append(
        CompareResult(
            name="outer.checkcode_shape",
            ok=check_ok,
            detail=f"len={len(checkcode)} value_case={'lower' if check_ok else 'n/a'}",
        )
    )
    return results


def _compare_common_trace(trace: dict[str, Any]) -> list[CompareResult]:
    endpoint = str(trace.get("endpoint", ""))
    results: list[CompareResult] = []
    request = trace.get("request")
    if not isinstance(request, dict):
        return [CompareResult(name=f"{endpoint}.request", ok=False, detail="request missing")]

    outer = request.get("outer")
    if not isinstance(outer, dict):
        return [CompareResult(name=f"{endpoint}.request.outer", ok=False, detail="request.outer missing")]

    for result in _compare_common_outer(outer):
        results.append(
            CompareResult(
                name=f"{endpoint}.{result.name}",
                ok=result.ok,
                detail=result.detail,
            )
        )

    response = trace.get("response")
    if not isinstance(response, dict):
        results.append(CompareResult(name=f"{endpoint}.response", ok=False, detail="response missing"))
        return results

    decoded = response.get("decoded")
    if not isinstance(decoded, dict):
        results.append(CompareResult(name=f"{endpoint}.response.decoded", ok=False, detail="decoded missing"))
        return results

    code = str(decoded.get("code", ""))
    results.append(
        CompareResult(
            name=f"{endpoint}.response.code_shape",
            ok=bool(code),
            detail=f"code={code!r}",
        )
    )
    return results


def _collect_common_trace_results(traces: list[dict[str, Any]]) -> list[CompareResult]:
    results: list[CompareResult] = []
    for trace in traces:
        endpoint = trace.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            continue
        results.extend(_compare_common_trace(trace))
    return results


def _compare_verify_trace(verify_trace: dict[str, Any], content_key: str) -> list[CompareResult]:
    results: list[CompareResult] = []
    request = verify_trace.get("request", {})
    outer = request.get("outer", {}) if isinstance(request, dict) else {}
    if not isinstance(outer, dict):
        return [CompareResult(name="verify.outer.present", ok=False, detail="request.outer missing")]

    results.extend(_compare_common_outer(outer))

    user_type = str(outer.get("userType", ""))
    results.append(
        CompareResult(
            name="verify.outer.userType",
            ok=user_type == "1",
            detail=f"value={user_type!r} expected='1'",
        )
    )

    encry_data = outer.get("encryData")
    if not isinstance(encry_data, str) or not encry_data:
        results.append(CompareResult(name="verify.inner.decrypt", ok=False, detail="missing encryData"))
        return results

    try:
        inner_text = aes_decrypt_utf8(encry_data, content_key)
        inner = json.loads(inner_text)
    except Exception as exc:
        results.append(CompareResult(name="verify.inner.decrypt", ok=False, detail=str(exc)))
        return results

    if not isinstance(inner, dict):
        results.append(CompareResult(name="verify.inner.type", ok=False, detail=f"type={type(inner).__name__}"))
        return results

    missing = [key for key in VERIFY_INNER_KEYS if key not in inner]
    results.append(
        CompareResult(
            name="verify.inner.required_keys",
            ok=not missing,
            detail="missing=" + (", ".join(missing) if missing else "none"),
        )
    )

    results.append(
        CompareResult(
            name="verify.inner.functionType",
            ok=str(inner.get("functionType", "")) == "remoteControl",
            detail=f"value={inner.get('functionType')!r}",
        )
    )

    cmd_pwd = str(inner.get("commandPwd", ""))
    results.append(
        CompareResult(
            name="verify.inner.commandPwd_shape",
            ok=_is_upper_hex(cmd_pwd, 32),
            detail=f"len={len(cmd_pwd)}",
        )
    )

    rnd = str(inner.get("random", ""))
    results.append(
        CompareResult(
            name="verify.inner.random_shape",
            ok=_is_upper_hex(rnd, 32),
            detail=f"len={len(rnd)}",
        )
    )

    response = verify_trace.get("response", {})
    decoded = response.get("decoded", {}) if isinstance(response, dict) else {}
    if not isinstance(decoded, dict):
        results.append(CompareResult(name="verify.response.outer", ok=False, detail="response.decoded missing"))
        return results

    code = str(decoded.get("code", ""))
    results.append(
        CompareResult(
            name="verify.response.code",
            ok=code == "0",
            detail=f"code={code!r}",
        )
    )

    respond_data = decoded.get("respondData")
    if code != "0":
        results.append(
            CompareResult(
                name="verify.response.respondData",
                ok=True,
                detail="not evaluated because response code is non-zero",
            )
        )
        return results

    if not respond_data:
        results.append(
            CompareResult(
                name="verify.response.respondData",
                ok=True,
                detail="respondData empty/missing accepted (code=0)",
            )
        )
        return results

    if not isinstance(respond_data, str):
        results.append(
            CompareResult(
                name="verify.response.respondData",
                ok=False,
                detail=f"unexpected type={type(respond_data).__name__}",
            )
        )
        return results

    try:
        decrypted = aes_decrypt_utf8(respond_data, content_key)
    except Exception as exc:
        results.append(
            CompareResult(
                name="verify.response.decrypt",
                ok=False,
                detail=str(exc),
            )
        )
        return results

    results.append(
        CompareResult(
            name="verify.response.decrypt",
            ok=True,
            detail=f"plaintext_len={len(decrypted)}",
        )
    )
    return results


def _print_results(results: list[CompareResult]) -> None:
    width = max((len(result.name) for result in results), default=20)
    print("\nComparability report")
    print("-" * (width + 24))
    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"{result.name:<{width}}  {status:<4}  {result.detail}")

    failures = [result for result in results if not result.ok]
    print("-" * (width + 24))
    print(f"Summary: {len(results) - len(failures)} OK, {len(failures)} FAIL")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live pyBYD shared-user parity checks")
    parser.add_argument(
        "--vin",
        default=None,
        help="Target VIN. If omitted, first VIN from get_vehicles() is used.",
    )
    parser.add_argument(
        "--json-trace",
        action="store_true",
        help="Print captured transport traces as JSON (redacted by transport).",
    )
    parser.add_argument(
        "--layers",
        action="store_true",
        help=("Print all request/response layers for each endpoint, including best-effort decrypted inner payloads."),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Return non-zero when any comparability check fails. "
            "Without --strict, verify API non-zero responses are reported but tolerated."
        ),
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    config = _load_shared_config()
    control_pin = _load_shared_control_pin()
    traces: list[dict[str, Any]] = []

    async with BydClient(config) as client:
        _install_transport_trace(client, traces)
        vehicles = await client.get_vehicles()
        if not vehicles:
            print("No vehicles returned by account")
            return 2

        selected_vin = args.vin or vehicles[0].vin
        if not selected_vin:
            print("Selected vehicle has empty VIN")
            return 2

        verify_call_results: list[CompareResult] = []
        try:
            await client.verify_control_password(selected_vin, command_pwd=control_pin)
            verify_call_results.append(
                CompareResult(
                    name="verify.call",
                    ok=True,
                    detail="verify_control_password returned success",
                )
            )
        except BydApiError as exc:
            verify_call_results.append(
                CompareResult(
                    name="verify.call",
                    ok=False,
                    detail=f"BydApiError code={exc.code!r} endpoint={exc.endpoint!r} message={exc}",
                )
            )

        session = await client.ensure_session()
        verify_trace = _find_latest_trace(traces, "/vehicle/vehicleswitch/verifyControlPassword")
        if verify_trace is None:
            print("Missing trace for /vehicle/vehicleswitch/verifyControlPassword")
            return 2

        results = _collect_common_trace_results(traces)
        results.extend(verify_call_results)
        results.extend(_compare_verify_trace(verify_trace, session.content_key()))

    if args.json_trace:
        print(json.dumps(traces, indent=2, ensure_ascii=False, sort_keys=True))

    if args.layers:
        layer_dump = _build_layered_trace_dump(
            traces,
            session_content_key=session.content_key(),
            login_key=pwd_login_key(config.password),
        )
        print("\nLayered request/response dump")
        print(json.dumps(layer_dump, indent=2, ensure_ascii=False, sort_keys=True))

    _print_results(results)

    failures = [result for result in results if not result.ok]
    if not failures:
        return 0
    if args.strict:
        return 1

    tolerated_failures = {
        "verify.call",
        "verify.response.code",
    }
    non_tolerated = [result for result in failures if result.name not in tolerated_failures]
    return 1 if non_tolerated else 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
