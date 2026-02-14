"""Internal command/control operations for :class:`pybyd.client.BydClient`.

These functions keep `client.py` small without changing the public API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from pybyd._api.control import poll_remote_control
from pybyd._api.control import verify_control_password as verify_control_password_api
from pybyd._api.smart_charging import save_charging_schedule as save_charging_schedule_api
from pybyd._api.smart_charging import toggle_smart_charging as toggle_smart_charging_api
from pybyd._api.vehicle_settings import rename_vehicle as rename_vehicle_api
from pybyd.models.command_responses import CommandAck, VerifyControlPasswordResponse
from pybyd.models.control import RemoteCommand, RemoteControlResult
from pybyd.models.control_params import (
    BatteryHeatParams,
    ClimateScheduleParams,
    ClimateStartParams,
    ControlCallOptions,
    ControlParams,
    SeatClimateParams,
)
from pybyd.models.requests import RenameVehicleRequest, ToggleSmartChargingRequest
from pybyd.models.smart_charging import SmartChargingSchedule
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection

if TYPE_CHECKING:
    from pybyd.client import BydClient


async def verify_control_password(
    client: BydClient,
    *,
    vin: str,
    command_pwd: str | None = None,
) -> VerifyControlPasswordResponse:
    resolved = client._resolve_command_pwd(command_pwd)
    if not resolved:
        raise ValueError("No control PIN available (set config.control_pin or pass command_pwd)")

    async def _call() -> VerifyControlPasswordResponse:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await verify_control_password_api(client._config, session, transport, vin, resolved)

    return await client._call_with_reauth(_call)


async def _remote_control(
    client: BydClient,
    *,
    vin: str,
    command: RemoteCommand,
    control_params: Mapping[str, Any] | ControlParams | None = None,
    command_pwd: str | None = None,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
) -> RemoteControlResult:
    resolved_pwd = client._require_command_pwd(command_pwd)

    control_params_map: dict[str, Any] | None
    if control_params is None:
        control_params_map = None
    elif isinstance(control_params, ControlParams):
        control_params_map = control_params.to_control_params_map()
    else:
        control_params_map = dict(control_params)

    async def _call() -> RemoteControlResult:
        session = await client.ensure_session()
        transport = client._require_transport()
        coordinator = client._mqtt
        return await poll_remote_control(
            client._config,
            session,
            transport,
            vin,
            command,
            control_params=control_params_map,
            command_pwd=resolved_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            mqtt_result_waiter=coordinator.wait_for_remote_control if coordinator else None,
            debug_recorder=None,
        )

    result: RemoteControlResult = await client._call_with_reauth(_call)
    client.store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.CONTROL,
            source=IngestionSource.HTTP,
            payload_timestamp=None,
            data=result.model_dump(exclude={"raw"}),
            raw=result.raw if isinstance(result.raw, dict) else {},
        )
    )
    return result


async def lock(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    optimistic_value = 2
    await client.apply_optimistic(
        vin,
        section=StateSection.REALTIME,
        patch={
            "left_front_door_lock": optimistic_value,
            "right_front_door_lock": optimistic_value,
            "left_rear_door_lock": optimistic_value,
            "right_rear_door_lock": optimistic_value,
            "sliding_door_lock": optimistic_value,
        },
    )
    try:
        result = await _remote_control(
            client,
            vin=vin,
            command=RemoteCommand.LOCK,
            command_pwd=opts.command_pwd,
            poll_attempts=opts.poll_attempts,
            poll_interval=opts.poll_interval,
        )
        if result.success:
            await client.apply_optimistic(
                vin,
                section=StateSection.REALTIME,
                patch={
                    "left_front_door_lock": optimistic_value,
                    "right_front_door_lock": optimistic_value,
                    "left_rear_door_lock": optimistic_value,
                    "right_rear_door_lock": optimistic_value,
                    "sliding_door_lock": optimistic_value,
                },
                ttl_seconds=0,
            )
        return result
    except Exception:
        await client.apply_optimistic(
            vin,
            section=StateSection.REALTIME,
            patch={
                "left_front_door_lock": 1,
                "right_front_door_lock": 1,
                "left_rear_door_lock": 1,
                "right_rear_door_lock": 1,
                "sliding_door_lock": 1,
            },
        )
        raise


async def unlock(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    optimistic_value = 1
    await client.apply_optimistic(
        vin,
        section=StateSection.REALTIME,
        patch={
            "left_front_door_lock": optimistic_value,
            "right_front_door_lock": optimistic_value,
            "left_rear_door_lock": optimistic_value,
            "right_rear_door_lock": optimistic_value,
            "sliding_door_lock": optimistic_value,
        },
    )
    try:
        result = await _remote_control(
            client,
            vin=vin,
            command=RemoteCommand.UNLOCK,
            command_pwd=opts.command_pwd,
            poll_attempts=opts.poll_attempts,
            poll_interval=opts.poll_interval,
        )
        if result.success:
            await client.apply_optimistic(
                vin,
                section=StateSection.REALTIME,
                patch={
                    "left_front_door_lock": optimistic_value,
                    "right_front_door_lock": optimistic_value,
                    "left_rear_door_lock": optimistic_value,
                    "right_rear_door_lock": optimistic_value,
                    "sliding_door_lock": optimistic_value,
                },
                ttl_seconds=0,
            )
        return result
    except Exception:
        await client.apply_optimistic(
            vin,
            section=StateSection.REALTIME,
            patch={
                "left_front_door_lock": 2,
                "right_front_door_lock": 2,
                "left_rear_door_lock": 2,
                "right_rear_door_lock": 2,
                "sliding_door_lock": 2,
            },
        )
        raise


async def start_climate(
    client: BydClient,
    *,
    vin: str,
    params: ClimateStartParams | None = None,
    preset: Literal["max_heat", "max_cool"] | None = None,
    options: ControlCallOptions | None = None,
    temperature: int | None = None,
    temperature_c: float | None = None,
    copilot_temperature: int | None = None,
    copilot_temperature_c: float | None = None,
    cycle_mode: int | None = None,
    time_span: int | None = None,
    ac_switch: int | None = None,
    air_accuracy: int | None = None,
    air_conditioning_mode: int | None = None,
    remote_mode: int | None = None,
    wind_level: int | None = None,
    wind_position: int | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    params = ClimateStartParams.from_inputs(
        params=params,
        preset=preset,
        temperature=temperature,
        temperature_c=temperature_c,
        copilot_temperature=copilot_temperature,
        copilot_temperature_c=copilot_temperature_c,
        cycle_mode=cycle_mode,
        time_span=time_span,
        ac_switch=ac_switch,
        air_accuracy=air_accuracy,
        air_conditioning_mode=air_conditioning_mode,
        remote_mode=remote_mode,
        wind_level=wind_level,
        wind_position=wind_position,
    )

    await client.apply_optimistic(vin, section=StateSection.HVAC, patch=params.optimistic_hvac_patch_on())
    try:
        result = await _remote_control(
            client,
            vin=vin,
            command=RemoteCommand.START_CLIMATE,
            control_params=params,
            command_pwd=opts.command_pwd,
            poll_attempts=opts.poll_attempts,
            poll_interval=opts.poll_interval,
        )
        if result.success:
            # Treat successful command ack as confirmation and keep the optimistic
            # state until a server snapshot arrives (do not rely on the default TTL).
            await client.apply_optimistic(
                vin,
                section=StateSection.HVAC,
                patch=params.optimistic_hvac_patch_on(),
                ttl_seconds=0,
            )
        return result
    except Exception:
        await client.apply_optimistic(vin, section=StateSection.HVAC, patch={"status": 0, "ac_switch": 0})
        raise


async def stop_climate(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    await client.apply_optimistic(vin, section=StateSection.HVAC, patch={"status": 0, "ac_switch": 0})
    try:
        result = await _remote_control(
            client,
            vin=vin,
            command=RemoteCommand.STOP_CLIMATE,
            command_pwd=opts.command_pwd,
            poll_attempts=opts.poll_attempts,
            poll_interval=opts.poll_interval,
        )
        if result.success:
            await client.apply_optimistic(
                vin,
                section=StateSection.HVAC,
                patch={"status": 0, "ac_switch": 0},
                ttl_seconds=0,
            )
        return result
    except Exception:
        await client.apply_optimistic(vin, section=StateSection.HVAC, patch={"status": 2})
        raise


async def flash_lights(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.FLASH_LIGHTS,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def close_windows(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.CLOSE_WINDOWS,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def find_car(
    client: BydClient,
    *,
    vin: str,
    options: ControlCallOptions | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.FIND_CAR,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def schedule_climate(
    client: BydClient,
    *,
    vin: str,
    params: ClimateScheduleParams | None = None,
    options: ControlCallOptions | None = None,
    booking_id: int | None = None,
    booking_time: int | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    params = ClimateScheduleParams.from_schedule_inputs(params=params, booking_id=booking_id, booking_time=booking_time)
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.SCHEDULE_CLIMATE,
        control_params=params,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def set_seat_climate(
    client: BydClient,
    *,
    vin: str,
    params: SeatClimateParams | None = None,
    options: ControlCallOptions | None = None,
    main_heat: int | None = None,
    main_ventilation: int | None = None,
    copilot_heat: int | None = None,
    copilot_ventilation: int | None = None,
    lr_seat_heat: int | None = None,
    lr_seat_ventilation: int | None = None,
    rr_seat_heat: int | None = None,
    rr_seat_ventilation: int | None = None,
    steering_wheel_heat: int | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    params = SeatClimateParams.from_inputs(
        params=params,
        main_heat=main_heat,
        main_ventilation=main_ventilation,
        copilot_heat=copilot_heat,
        copilot_ventilation=copilot_ventilation,
        lr_seat_heat=lr_seat_heat,
        lr_seat_ventilation=lr_seat_ventilation,
        rr_seat_heat=rr_seat_heat,
        rr_seat_ventilation=rr_seat_ventilation,
        steering_wheel_heat=steering_wheel_heat,
    )
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.SEAT_CLIMATE,
        control_params=params,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def set_battery_heat(
    client: BydClient,
    *,
    vin: str,
    params: BatteryHeatParams | None = None,
    options: ControlCallOptions | None = None,
    on: bool | None = None,
    command_pwd: str | None = None,
    poll_attempts: int | None = None,
    poll_interval: float | None = None,
) -> RemoteControlResult:
    params = BatteryHeatParams.from_inputs(params=params, on=on)
    opts = client._resolve_call_options(
        options=options,
        command_pwd=command_pwd,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
    )
    return await _remote_control(
        client,
        vin=vin,
        command=RemoteCommand.BATTERY_HEAT,
        control_params=params,
        command_pwd=opts.command_pwd,
        poll_attempts=opts.poll_attempts,
        poll_interval=opts.poll_interval,
    )


async def save_charging_schedule(
    client: BydClient,
    *,
    vin: str,
    schedule: SmartChargingSchedule | None = None,
    target_soc: int | None = None,
    start_hour: int | None = None,
    start_minute: int | None = None,
    end_hour: int | None = None,
    end_minute: int | None = None,
) -> CommandAck:
    async def _call() -> CommandAck:
        session = await client.ensure_session()
        transport = client._require_transport()

        effective = schedule
        if effective is None:
            if (
                target_soc is None
                or start_hour is None
                or start_minute is None
                or end_hour is None
                or end_minute is None
            ):
                raise ValueError("Either schedule must be provided, or all schedule parameters must be set")
            effective = SmartChargingSchedule(
                vin=vin,
                target_soc=target_soc,
                start_hour=start_hour,
                start_minute=start_minute,
                end_hour=end_hour,
                end_minute=end_minute,
                smart_charge_switch=1,
                raw={},
            )

        if effective.target_soc is None:
            raise ValueError("schedule.target_soc must not be None")
        if effective.start_hour is None or effective.start_minute is None:
            raise ValueError("schedule.start_hour/start_minute must not be None")
        if effective.end_hour is None or effective.end_minute is None:
            raise ValueError("schedule.end_hour/end_minute must not be None")

        return await save_charging_schedule_api(
            client._config,
            session,
            transport,
            vin,
            target_soc=effective.target_soc,
            start_hour=effective.start_hour,
            start_minute=effective.start_minute,
            end_hour=effective.end_hour,
            end_minute=effective.end_minute,
        )

    return await client._call_with_reauth(_call)


async def toggle_smart_charging(client: BydClient, *, vin: str, enable: bool) -> CommandAck:
    request = ToggleSmartChargingRequest(vin=vin, enable=enable)

    async def _call() -> CommandAck:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await toggle_smart_charging_api(client._config, session, transport, request.vin, enable=request.enable)

    return await client._call_with_reauth(_call)


async def rename_vehicle(client: BydClient, *, vin: str, name: str) -> CommandAck:
    request = RenameVehicleRequest(vin=vin, name=name)

    async def _call() -> CommandAck:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await rename_vehicle_api(client._config, session, transport, request.vin, name=request.name)

    return await client._call_with_reauth(_call)
