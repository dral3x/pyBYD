# BYD Overseas API Protocol Reference

> **Base URL:** `https://dilinkappoversea-eu.byd.auto`
>
> **Sources:** [Niek/BYD-re URLs.md](https://github.com/Niek/BYD-re/blob/main/URLs.md), TA2k's v3.2.2 APK extraction, live probe results
>
> **Last updated:** 2026-02-11

---

## Table of Contents

- [Transport Layer](#transport-layer)
- [Authentication Flow](#authentication-flow)
- [Error Codes](#error-codes)
- [Account & Auth](#account--auth)
- [Vehicle List](#vehicle-list)
- [Vehicle Realtime Data](#vehicle-realtime-data)
- [GPS & Location](#gps--location)
- [Vehicle Control](#vehicle-control)
- [Smart Charge](#smart-charge)
- [Vehicle Settings & Switches](#vehicle-settings--switches)
- [Vehicle Empower (Sharing)](#vehicle-empower-sharing)
- [Used Car Transfer](#used-car-transfer)
- [NFC Digital Key](#nfc-digital-key)
- [Bluetooth Key](#bluetooth-key)
- [OTA Updates](#ota-updates)
- [Sentinel / Standby](#sentinel--standby)
- [External / Widget APIs](#external--widget-apis)
- [App Config & Resources](#app-config--resources)
- [Agreements & Common](#agreements--common)
- [Charge Platform](#charge-platform)
- [User Settings & Profile](#user-settings--profile)
- [Message Center](#message-center)
- [NPS & Feedback](#nps--feedback)
- [Fleet Management (FMS)](#fleet-management-fms)
- [User UI Routes (non-API)](#user-ui-routes-non-api)
- [404 / Non-existent Endpoints](#404--non-existent-endpoints)
- [Write-only / Mutating Endpoints (not probed)](#write-only--mutating-endpoints-not-probed)

---

## Transport Layer

Every request goes through a Bangcle white-box AES envelope layer.

### HTTP Request

```
POST {base_url}{endpoint}
Content-Type: application/json; charset=UTF-8
User-Agent: okhttp/4.12.0
Accept-Encoding: identity
Cookie: <session cookies from previous responses>

{"request": "<bangcle_encoded_string>"}
```

The `request` value is the Bangcle-encoded JSON string of the **outer payload**.

### HTTP Response

```json
{"response": "<bangcle_encoded_string>"}
```

The `response` value is Bangcle-decoded to produce the **outer response JSON**.

### Bangcle Envelope

The Bangcle codec uses white-box AES with 8 lookup tables extracted from the APK's `libdatajar.so`. It performs CBC encryption/decryption with a zero IV, using pre-computed tables that embed the key schedule. See `_crypto/bangcle.py` for implementation.

### Outer Payload Structure (Login)

For the login endpoint, the outer payload is:

```json
{
  "countryCode": "NL",
  "encryData": "<AES-encrypted inner payload, hex>",
  "functionType": "pwdLogin",
  "identifier": "<username/email>",
  "identifierType": "0",
  "imeiMD5": "<device IMEI MD5>",
  "isAuto": "1",
  "language": "en",
  "reqTimestamp": "<ms since epoch>",
  "sign": "<SHA1 signature>",
  "signKey": "<password>",
  "ostype": "and",
  "imei": "<device IMEI>",
  "mac": "<device MAC>",
  "model": "<device model>",
  "sdk": "<Android SDK version>",
  "mod": "<device manufacturer>",
  "serviceTime": "<ms since epoch>",
  "checkcode": "<MD5 checkcode>"
}
```

The `encryData` is AES-128-CBC encrypted using `MD5(password)` as the key. The inner payload contains device and app version info.

### Outer Payload Structure (Token-authenticated)

For all post-login endpoints:

```json
{
  "countryCode": "NL",
  "encryData": "<AES-encrypted inner payload, hex>",
  "identifier": "<user_id>",
  "imeiMD5": "<device IMEI MD5>",
  "language": "en",
  "reqTimestamp": "<ms since epoch>",
  "sign": "<SHA1 signature>",
  "ostype": "and",
  "imei": "<device IMEI>",
  "mac": "<device MAC>",
  "model": "<device model>",
  "sdk": "<Android SDK version>",
  "mod": "<device manufacturer>",
  "serviceTime": "<ms since epoch>",
  "checkcode": "<MD5 checkcode>"
}
```

The `encryData` is AES-128-CBC encrypted using `MD5(encryToken)` as the key (the `content_key`).

### Outer Response Structure

```json
{
  "code": "0",
  "message": "SUCCESS",
  "respondData": "<AES-encrypted response data, hex>"
}
```

The `respondData` is AES-128-CBC decrypted using the same `content_key`.

### Signature Computation

1. Build a dict of all inner fields + `countryCode`, `identifier`, `imeiMD5`, `language`, `reqTimestamp`
2. Sort keys, concatenate as `key1=value1&key2=value2&...`
3. Append the sign key: `&key=<MD5(signToken)>` (or `MD5(password)` for login)
4. Compute `SHA1` of the result, output as uppercase hex

### Checkcode Computation

`MD5` of selected outer fields concatenated, used as integrity check.

### Standard Inner Payload Fields

All token-authenticated requests include these base fields in the encrypted inner payload:

```json
{
  "deviceType": "0",
  "imeiMD5": "<device IMEI MD5>",
  "networkType": "wifi",
  "random": "<32-char random hex>",
  "timeStamp": "<ms since epoch>",
  "version": "220"
}
```

Endpoint-specific fields are merged into this base.

---

## Authentication Flow

### Login: `POST /app/account/login`

**Inner payload (encrypted with `MD5(password)`):**

```json
{
  "appInnerVersion": "220",
  "appVersion": "2.2.1",
  "deviceName": "XIAOMIPOCO F1",
  "deviceType": "0",
  "imeiMD5": "00000000000000000000000000000000",
  "isAuto": "1",
  "mobileBrand": "XIAOMI",
  "mobileModel": "POCO F1",
  "networkType": "wifi",
  "osType": "15",
  "osVersion": "35",
  "random": "<32-char hex>",
  "softType": "0",
  "timeStamp": "<ms since epoch>",
  "timeZone": "Europe/Amsterdam"
}
```

**Response `respondData` (decrypted):**

```json
{
  "token": {
    "userId": "1434",
    "signToken": "<sign token string>",
    "encryToken": "<encryption token string>"
  }
}
```

The `signToken` and `encryToken` are used to derive session keys:
- `content_key = MD5(encryToken)` — for AES encrypt/decrypt of inner payloads
- `sign_key = MD5(signToken)` — for request signature computation

---

## Error Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `500` | Server exception (generic) |
| `1001` | Service exception — generic server error or missing required field |
| `1005` | Service error — authentication/parameter issue |
| `1007` | Validation error — unexpected field in request |
| `1009` | Timeout / data not ready (async result not yet available) |
| `1010` | Permission denied or missing required context |
| `2006` | Data loading abnormal |
| `6065` | Invalid QR code |
| `6071` | Weak network signal around vehicle |
| `400291003` | Validation failed (charge platform specific) |
| `N00002` | NFC parameter validation failed (参数校验失败) |

---

## Account & Auth

### `POST /app/account/getAllListByUserId`

Get all vehicles associated with the authenticated user.

**Extra inner fields:** None (standard fields only)

**Response `respondData`:** Array of vehicle objects

```json
[
  {
    "autoAlias": "EE24504",
    "autoBoughtTime": 1655988173000,
    "autoPlate": "EE24504",
    "bluetoothInfo": null,
    "brandId": 0,
    "brandName": "BYD",
    "carType": 0,
    "cfPic": {
      "clrCode": "MR0001",
      "flag": 0,
      "picDoorZipUrl": "",
      "picMainUrl": "https://yunservice-storage-eu-gcp.byd.auto/autoPic/prod/...",
      "picSetUrl": "https://yunservice-storage-eu-gcp.byd.auto/autoPic/prod/...",
      "picTireUrl": ""
    },
    "cloudServiceStatue": "",
    "crmModelId": "",
    "crmStyleId": "",
    "dealerRegionCode": "",
    "defaultCar": 1,
    "empowerType": 2,
    "energyType": "0",
    "modelId": 1,
    "modelName": "Tang EV",
    "openCloudServiceStatue": false,
    "outModelType": "Tang EV",
    "permissionStatus": 2,
    "rangeDetailList": [],
    "tboxVersion": "3",
    "totalMileage": 58987,
    "userManualUrl": "",
    "vehicleFunLearnInfo": {
      "acCurrentFunctionLimitLearnInfo": -1,
      "airAccuracy": 1,
      "airRange": 1,
      "batteryHeating": 0,
      "bookingCar": -1,
      "bookingCharge": -1,
      "domainControlLearnInfo": 1,
      "energyLearnInfo": 0,
      "gpsLearnInfo": 1,
      "nfcDigitalLearnInfo": 0,
      "otaUpgrade": -1,
      "rapidTempUpAndDown": 0,
      "refrigeratorLearnInfo": -1,
      "rudderType": 1,
      "sentryStatusLearnInfo": 0,
      "steeringWheelHeating": 1,
      "vehicleSafetyVerified": 0
    },
    "vehicleState": "1",
    "vehicleTimeZone": "",
    "vehicleType": "",
    "vin": "LC0CF4CD7N1000375",
    "yunActiveTime": 1655988182000
  }
]
```

> **Note:** Returns `[]` for shared/empowered users who don't own the vehicle.

---

### `POST /app/account/user/detail`

Get user profile details.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "birthday": "",
  "nickName": "BYD110504292",
  "nickNameTime": "",
  "profilePic": "https://fr-bydapp-cache.byd.auto/fr/portal/.../image.png",
  "registerCountry": "NO",
  "userId": "1434"
}
```

---

### `POST /app/account/getBindStatus`

Get social login (OAuth) bind status.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "appleBindStatus": false,
  "facebookBindStatus": false,
  "googleBindStatus": false
}
```

---

### `POST /app/account/getAccountState`

**Status:** Error `1005` — likely requires additional parameters not yet identified.

---

### `POST /app/account/getServerCurrentTime`

**Status:** Error `1005` — likely requires additional parameters.

---

### `POST /app/account/getValidateCodeLogin`

Request a verification code for code-based login.

**Status:** Error `1005` — requires phone/email parameters.

---

### `POST /app/account/checkRegistVerifyData`

Validate registration verification data.

**Status:** Error `1001` — requires verification parameters.

---

### `POST /app/account/logout`

Logout the current session.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/account/bind`

Bind a social account (Apple/Google/Facebook).

**Status:** Not probed (mutating endpoint).

---

### `POST /app/account/modifyDefaultCar`

Change the default vehicle for the account.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/account/rejectCancellUser`

Reject account cancellation request.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/account/setLoginPassword`

Set/change login password.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/account/user/modify`

Modify user profile.

**Status:** Not probed (mutating endpoint).

---

## Vehicle List

### `POST /app/vehicle/allCarsForEachBrandByUser`

Get model names of all vehicles grouped by brand. Works for both owner and shared users.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "bydCarOutModleNames": ["Tang EV"],
  "denzaCarOutModleNames": [],
  "ywCarOutModleNames": []
}
```

> **Note:** Returns model names only, **no VINs**. This is the only endpoint that acknowledges shared vehicles without knowing the VIN.

---

### `POST /app/vehicle/getPaginatedVehicleListByUserId`

**Status:** Error `1001` — broken for all users (owner and shared). Likely deprecated.

---

### `POST /app/vehicle/single`

Get details for a single vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` — service exception for all tested parameter combinations.

---

## Vehicle Realtime Data

### `POST /vehicleInfo/vehicle/vehicleRealTimeRequest`

Trigger a realtime data request to the vehicle's T-Box. Returns cached data or a `requestSerial` for polling.

**Extra inner fields:**

```json
{
  "vin": "<VIN>",
  "energyType": "0",
  "tboxVersion": "3"
}
```

**Response `respondData`:**

```json
{
  "onlineState": 0,
  "connectState": -1,
  "vehicleState": 0,
  "requestSerial": "3BDBE8147B1247C3B0384C6B3AB3B0C6",

  "elecPercent": 0,
  "powerBattery": 0,
  "enduranceMileage": 0,
  "evEndurance": 0,
  "enduranceMileageV2": 0,
  "enduranceMileageV2Unit": "--",
  "totalMileage": 0,
  "totalMileageV2": 0,
  "totalMileageV2Unit": "--",
  "speed": 0,
  "tempInCar": 0,
  "oilEndurance": 0,
  "oilPercent": 0,
  "totalOil": 0.0,

  "chargingState": -1,
  "chargeState": 0,
  "waitStatus": 0,
  "fullHour": -1,
  "fullMinute": -1,
  "remainingHours": 0,
  "remainingMinutes": 0,
  "bookingChargeState": 0,
  "bookingChargingHour": 0,
  "bookingChargingMinute": 0,

  "leftFrontDoor": 0,
  "rightFrontDoor": 0,
  "leftRearDoor": 0,
  "rightRearDoor": 0,
  "trunkLid": 0,
  "slidingDoor": 0,
  "forehold": 0,

  "leftFrontDoorLock": 0,
  "rightFrontDoorLock": 0,
  "leftRearDoorLock": 0,
  "rightRearDoorLock": 0,
  "slidingDoorLock": 0,

  "leftFrontWindow": 0,
  "rightFrontWindow": 0,
  "leftRearWindow": 0,
  "rightRearWindow": 0,
  "skylight": 0,

  "leftFrontTirepressure": 0.0,
  "rightFrontTirepressure": 0.0,
  "leftRearTirepressure": 0.0,
  "rightRearTirepressure": 0.0,
  "leftFrontTireStatus": 0,
  "rightFrontTireStatus": 0,
  "leftRearTireStatus": 0,
  "rightRearTireStatus": 0,
  "tirePressUnit": 3,
  "tirepressureSystem": 0,
  "rapidTireLeak": 0,

  "mainSettingTemp": 0,
  "mainSettingTempNew": 0.0,
  "mainSeatHeatState": 0,
  "mainSeatVentilationState": 0,
  "copilotSeatHeatState": 0,
  "copilotSeatVentilationState": 0,
  "steeringWheelHeatState": 0,
  "lrSeatHeatState": 0,
  "lrSeatVentilationState": 0,
  "rrSeatHeatState": 0,
  "rrSeatVentilationState": 0,
  "lrThirdHeatState": 0,
  "lrThirdVentilationState": 0,
  "rrThirdHeatState": 0,
  "rrThirdVentilationState": 0,
  "airRunState": 0,

  "totalPower": 0.0,
  "totalEnergy": "--",
  "nearestEnergyConsumption": "--",
  "nearestEnergyConsumptionUnit": "--",
  "recent50kmEnergy": "--",

  "powerSystem": 0,
  "engineStatus": 0,
  "epb": 0,
  "eps": 0,
  "esp": 0,
  "abs": 0,
  "svs": 0,
  "srs": 0,
  "ect": 0,
  "ectValue": 0,
  "pwr": 0,
  "gl": 0.0,
  "ins": 0,
  "okLight": 0,
  "upgradeStatus": 0,
  "sentryStatus": 0,
  "batteryHeatState": 0,
  "chargeHeatState": 0,
  "oilPressureSystem": 0,
  "brakingSystem": 0,
  "chargingSystem": 0,
  "steeringSystem": 0,
  "powerBatteryConnection": 0,
  "powerGear": 0,
  "rate": 0,
  "time": 0
}
```

**Key field meanings:**
- `onlineState`: 0=unknown, 1=online, 2=offline
- `connectState`: -1=unknown, 0=disconnected, 1=connected
- `vehicleState`: 0=off, 1=on
- `chargingState`: -1=unknown, 0=not charging, >0=charging
- Door/lock/window values: 0=closed/locked, 1=open/unlocked
- `tirePressUnit`: 1=kPa, 2=psi, 3=bar
- `sentryStatus`: 0=off, 1=on

---

### `POST /vehicleInfo/vehicle/vehicleRealTimeResult`

Poll for realtime data using the `requestSerial` from the trigger request.

**Extra inner fields:**

```json
{
  "vin": "<VIN>",
  "energyType": "0",
  "tboxVersion": "3",
  "requestSerial": "<serial from trigger>"
}
```

**Response:** Same structure as `vehicleRealTimeRequest`, but with live data populated when `onlineState` = 1.

---

### `POST /vehicleInfo/vehicle/getTapPosition`

Get the gear/tap position status.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "status": 1
}
```

---

### `POST /vehicleInfo/vehicle/getRefrigeratorDoorStatus`

Get refrigerator door status (vehicles with built-in refrigerator).

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "vin": "LC0CF4CD7N1000375"
}
```

---

### `POST /vehicleInfo/vehicle/getYunStatus`

Get cloud (Yun) connectivity and privacy status.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "operBehavior": "1",
  "funVersion": "0",
  "createTime": "2024-11-08T06:58:26.000+00:00",
  "yunStatus": "1",
  "authStatus": "1",
  "vin": "LC0CF4CD7N1000375",
  "updateTime": "2024-11-08T06:58:26.000+00:00",
  "id": 88878,
  "operTime": "2024-11-08 07:58:26",
  "privacyVersion": "47.20230625"
}
```

---

### `POST /vehicleInfo/vehicle/getEnergyConsumption`

Get energy consumption data.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` — may require additional parameters or be model-specific.

---

### `POST /vehicleInfo/auth/getAllSimCurPage`

Get SIM card info for the vehicle's T-Box.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` — may require ICCID or other SIM parameters.

---

### `POST /vehicleInfo/auth/getPortalUrlByIccid`

Get the carrier portal URL for the vehicle's SIM card.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response:** Code `0` with empty `respondData` (likely needs `iccid` parameter).

---

## GPS & Location

### `POST /control/getGpsInfo`

Trigger an asynchronous GPS data request to the vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "requestSerial": "8DCF2FB9A17646228A7260589660AB63"
}
```

Use the `requestSerial` to poll `/control/getGpsInfoResult`.

---

### `POST /control/getGpsInfoResult`

Poll for GPS data result.

**Extra inner fields:**

```json
{
  "vin": "<VIN>",
  "requestSerial": "<serial from getGpsInfo>"
}
```

**Response `respondData` (when ready):**

```json
{
  "latitude": 59.123456,
  "longitude": 10.654321,
  "speed": 0,
  "direction": 180,
  "gpsTimeStamp": 1770817900000,
  "requestSerial": "8DCF2FB9A17646228A7260589660AB63"
}
```

**Status:** Returns `1009` when result is not yet available. Poll with delay.

---

### `POST /positionServices/vehicleLocation`

Get vehicle location directly.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `500` — service exception. May be deprecated or require different parameters.

---

## Vehicle Control

### `POST /control/getStatusNow`

Get current HVAC/climate control status.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "statusNow": {
    "acSwitch": 0,
    "airConditioningMode": 0,
    "airConditionTempRange": 0,
    "airTempLevel": 0,
    "copilotSeatHeatState": 0,
    "copilotSeatVentilationState": 0,
    "copilotSettingTemp": 0,
    "copilotSettingTempNew": 0.0,
    "cycleChoice": 1,
    "electricDefrostStatus": 0,
    "firstWarm": 0,
    "firstWind": 0,
    "frontAirSumPattern": 0,
    "frontDefrostStatus": 0,
    "lrSeatHeatState": 0,
    "lrSeatVentilationState": 0,
    "lrThirdHeatState": 0,
    "lrThirdVentilationState": 0,
    "mainSeatHeatState": 0,
    "mainSeatVentilationState": 0,
    "mainSettingTemp": 0,
    "mainSettingTempNew": 0.0,
    "pm": 0,
    "pm25StateOutCar": 0,
    "rapidDecreaseTempState": 0,
    "rapidIncreaseTempState": 0,
    "refrigeratorDoorState": 0,
    "refrigeratorState": 0,
    "rrSeatHeatState": 0,
    "rrSeatVentilationState": 0,
    "rrThirdHeatState": 0,
    "rrThirdVentilationState": 0,
    "secondWarm": 0,
    "secondWind": 0,
    "status": 0,
    "steeringWheelHeatState": 0,
    "temp": 0,
    "tempInCar": -129,
    "tempOutCar": 0,
    "timeChoice": 1,
    "whetherSupportAdjustTemp": 1,
    "windMode": 0,
    "windPosition": 0,
    "wiperHeatStatus": 0
  }
}
```

**Key field meanings:**
- `acSwitch`: 0=off, 1=on
- `cycleChoice`: 1=external air, 2=recirculation
- `tempInCar`: interior temperature (°C, -129=unavailable)
- `mainSettingTempNew`/`copilotSettingTempNew`: set temperature (°C)
- `*HeatState`: seat/steering wheel heating level (0=off)
- `*VentilationState`: seat ventilation level (0=off)
- `rapidIncreaseTempState`/`rapidDecreaseTempState`: rapid heating/cooling active

---

### `POST /control/remoteControl`

Send a remote control command to the vehicle.

**Extra inner fields:**

```json
{
  "vin": "<VIN>",
  "instructionCode": "<command code>"
}
```

**Command codes:**

| Code | Command |
|------|---------|
| `101` | Lock doors |
| `102` | Unlock doors |
| `111` | Turn on A/C |
| `112` | Turn off A/C |
| `121` | Open trunk |
| `141` | Close windows |
| `301` | Flash lights |
| `302` | Honk horn |

**Response `respondData`:**

```json
{
  "controlState": 0,
  "requestSerial": "<serial for polling>"
}
```

`controlState`: 0=pending, 1=success, 2=failure

---

### `POST /control/remoteControlResult`

Poll for remote control command result.

**Extra inner fields:**

```json
{
  "vin": "<VIN>",
  "instructionCode": "<command code>",
  "requestSerial": "<serial from remoteControl>"
}
```

**Response `respondData`:**

```json
{
  "controlState": 1,
  "requestSerial": "<serial>"
}
```

---

### `POST /control/remoteControlBatteryHeat`

Trigger battery pre-heating command.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Not probed (mutating endpoint).

---

### `POST /control/remoteControlBatteryHeatResult`

Poll for battery heat control result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Returns `1009` (no pending request).

---

### `POST /control/getBookingList`

Get scheduled A/C pre-conditioning bookings.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response:** Code `0`, empty `respondData` (no bookings configured).

---

### `POST /control/getRefrigeratorNow`

Get current refrigerator status (for vehicles with built-in refrigerator).

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` — vehicle may not support this feature.

---

### `POST /control/appBindingVehicle`

Bind a vehicle using a QR code.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `6065` — "Invalid QR code" (requires actual QR code data).

---

## Smart Charge

### `POST /control/smartCharge/homePage`

Get smart charging homepage with battery state.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "fullHour": -1,
  "soc": 70,
  "fullMinute": -1,
  "vin": "LC0CF4CD7N1000375",
  "updateTime": 1770817882,
  "connectState": 0,
  "chargingState": 15,
  "waitStatus": 0
}
```

**Key field meanings:**
- `soc`: State of charge (percentage, 0-100)
- `chargingState`: 15=not charging (values vary by state)
- `connectState`: 0=not connected to charger
- `fullHour`/`fullMinute`: estimated time to full (-1=not applicable)
- `updateTime`: Unix timestamp of last data update

---

### `POST /control/smartCharge/changeChargeStatue`

Start or stop charging.

**Status:** Not probed (mutating endpoint).

---

### `POST /control/smartCharge/changeResult`

Poll for charge status change result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` (no pending change request).

---

### `POST /control/smartCharge/saveOrUpdate`

Save or update smart charge schedule.

**Status:** Not probed (mutating endpoint).

---

### `POST /control/smartCharge/saveOrUpdateJourney`

Save or update journey charge settings.

**Status:** Not probed (mutating endpoint).

---

## Vehicle Settings & Switches

### `POST /vehicle/vehicleswitch/getPushSwitchState`

Get push notification switch states for the vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
[
  {"state": 1, "type": 1},
  {"state": 1, "type": 2},
  {"state": 0, "type": 22},
  {"state": 1, "type": 41},
  {"state": 1, "type": 42},
  {"state": 1, "type": 701}
]
```

**Type meanings (inferred):**
- `1`: General notifications
- `2`: Vehicle alerts
- `22`: Marketing/promotional
- `41`/`42`: Security alerts
- `701`: Service reminders

---

### `POST /vehicle/vehicleswitch/getVinSwitchState`

Get VIN-level switch state.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "state": 2
}
```

---

### `POST /vehicle/vehicleswitch/updatePermissionInfo`

Read/update permission info for a vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response:** Code `0`, message "success", empty respondData.

---

### `POST /vehicle/vehicleswitch/getLatestConfig`

Get latest vehicle configuration.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001` — service exception.

---

### `POST /vehicle/vehicleswitch/getLatestWidgetConfig`

Get latest widget configuration.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `2006` — "Data loading abnormal".

---

### `POST /vehicle/vehicleswitch/getControlPasswordResult`

Get control password verification result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Returns `1009` (no pending verification).

---

### `POST /vehicle/vehicleswitch/setPushSwitchState`

Set push notification switch state.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/setVinSwitchState`

Set VIN switch state.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/modifyAutoAlias`

Change vehicle alias/nickname.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/modifyAutoPlate`

Change vehicle license plate number.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/setControlPassword`

Set a remote control password.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/modifyControlPassword`

Modify existing control password.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/modifyAllControlPassword`

Modify control password for all vehicles.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/verifyControlPassword`

Verify control password.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/vehicleswitch/updatePicColor`

Update vehicle picture/color.

**Status:** Not probed (mutating endpoint).

---

## Vehicle Empower (Sharing)

### `POST /vehicle/empower/check/isAllowAdd`

Check if sharing/empowerment can be added for a vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "code": "1010",
  "countCheckRes": false,
  "message": "Service error(1010)"
}
```

> **Note:** The outer response is code `0`, but the inner respondData contains its own nested error code.

---

### `POST /vehicle/empower/query/empowerRange`

Query the permission/scope range for an empowered (shared) vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "empowerControlPwdStatus": false,
  "data": [
    {
      "code": "2",
      "name": "Keys and control",
      "childList": [
        {
          "code": "21",
          "name": "Basic control",
          "childList": [],
          "rangeOrder": 11
        }
      ],
      "rangeOrder": 1
    },
    {
      "code": "3",
      "name": "Privacy",
      "childList": [
        {
          "code": "31",
          "name": "Vehicle location",
          "childList": [],
          "rangeOrder": 41
        }
      ],
      "rangeOrder": 4
    }
  ]
}
```

---

### `POST /vehicle/empower/query/permissionList`

Query list of empowered users for a vehicle.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010` — may require owner account.

---

### `POST /vehicle/empower/query/empowerDetailByVin`

Get empowerment details for a specific VIN.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /vehicle/empower/query/empowerHistory`

Get empower/sharing history.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /vehicle/empower/manage/add`

Add an empowered user to a vehicle.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/empower/manage/delete`

Remove an empowered user from a vehicle.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/empower/manage/edit`

Edit empowerment permissions.

**Status:** Not probed (mutating endpoint).

---

## Used Car Transfer

### `POST /vehicle/usedCar/checkVin`

Check if a VIN is eligible for used car transfer.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "code": "0",
  "message": "SUCCESS"
}
```

---

### `POST /vehicle/usedCar/getTips`

Get used car transfer tips/notifications.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "redStatus": false
}
```

---

### `POST /vehicle/usedCar/applyRecord`

Get used car transfer application records.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response:** Code `0`, empty `respondData` (no records).

---

### `POST /vehicle/usedCar/bindVehicle`

Bind a used car to account.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/usedCar/transferVehicle`

Transfer vehicle ownership.

**Status:** Not probed (mutating endpoint).

---

### `POST /vehicle/usedCar/removeVehicle`

Remove a vehicle from account.

**Status:** Not probed (mutating endpoint).

---

## NFC Digital Key

All NFC endpoints return outer code `0` but inner response indicates parameter validation failure. They likely require additional device-specific parameters (e.g., device NFC hardware ID, pairing data) beyond just the VIN.

### `POST /nfc/v2/klist`

List NFC keys (v2).

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response `respondData`:**

```json
{
  "msg": "参数校验失败。",
  "code": "N00002"
}
```

> All NFC v2 endpoints return `N00002` ("parameter validation failed"). Likely needs NFC-specific params like `deviceId`, `nfcToken`, etc.

---

### `POST /nfc/app/v1/c3/isCanShare`

Check if NFC key can be shared.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/isCanPass`

Check if NFC passthrough is available.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/isPaired`

Check if NFC key is paired.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/getPic`

Get NFC key picture/image.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/preopeningCheck`

Pre-opening NFC check.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/versionCheck`

Check NFC firmware version.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/getUwbFunc`

Get UWB (Ultra-Wideband) function status.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/getUwbFuncResult`

Get UWB function result.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/getUwbFuncStatus`

Get UWB function status check.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/getPassStatus`

Get NFC pass status.

**Response:** Same `N00002` error pattern.

---

### `POST /nfc/app/v1/c3/changeOwnerDevice`

Change the owner device for NFC.

**Status:** Not probed (mutating endpoint).

---

### `POST /nfc/app/v1/c3/pairing`

Initiate NFC pairing.

**Status:** Not probed (mutating endpoint).

---

### `POST /nfc/app/v1/c3/pairingpassword`

Set NFC pairing password.

**Status:** Not probed (mutating endpoint).

---

### `POST /nfc/app/v1/c3/setUwbFunc`

Set UWB function.

**Status:** Not probed (mutating endpoint).

---

### `POST /nfc/app/v1/delete`

Delete an NFC key.

**Status:** Not probed (mutating endpoint).

---

## Bluetooth Key

### `POST /control/bluetooth/activateKey`

Activate a Bluetooth key.

**Status:** Not probed (mutating endpoint).

---

### `POST /control/bluetooth/activateKeyResult`

Poll for Bluetooth key activation result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Response:** Error `6071` — "Weak network signal around the vehicle. Activation failed."

---

## OTA Updates

### `POST /control/otaUpgrade/getOtaVersion`

Get available OTA update version.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /control/otaUpgrade/bookingUpgrade`

Schedule an OTA upgrade.

**Status:** Not probed (mutating endpoint).

---

### `POST /control/otaUpgrade/cancelUpgrade`

Cancel a scheduled OTA upgrade.

**Status:** Not probed (mutating endpoint).

---

### `POST /control/otaUpgrade/upgradeOta`

Start an OTA upgrade.

**Status:** Not probed (mutating endpoint).

---

## Sentinel / Standby

### `POST /control/remoteControlPreSentinel`

Pre-check for sentinel (sentry/dashcam) mode.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1009` (async result not ready / no pending request).

---

### `POST /control/standby-vehicles/send`

Send standby vehicle command (sentinel mode activation).

**Status:** Not probed (mutating endpoint).

---

### `POST /control/standby-vehicles/send-result`

Poll for standby vehicle command result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1001`.

---

## External / Widget APIs

These endpoints appear to be for Apple Watch / Android widget integrations. All return `1010` with the standard auth envelope — they likely require a different authentication method (possibly widget-specific tokens).

### `POST /external/vehicle/vehicleRealTimeRequest`

Widget/watch realtime data request.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /external/vehicle/vehicleRealTimeResult`

Widget/watch realtime data result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /external/widget/getControlItem`

Get widget control items.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /external/widget/setControlItem`

Set widget control items.

**Status:** Not probed (mutating endpoint).

---

### `POST /externalControl/remoteControl`

External remote control (from widget/watch).

**Status:** Not probed (mutating endpoint).

---

### `POST /externalControl/remoteControlResult`

External remote control result.

**Extra inner fields:** `{"vin": "<VIN>"}`

**Status:** Error `1010`.

---

### `POST /widget/setting`

Widget settings.

**Extra inner fields:** None

**Status:** Error `500` — service exception.

---

## App Config & Resources

### `POST /app/emqAuth/getEmqBrokerIp`

Get MQTT broker connection info for push notifications and live events.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "emqBorker": "agoversea-eu-gcp.byd.auto:8883"
}
```

> The MQTT broker uses TLS on port 8883.

---

### `POST /common/appsoft/checkAppSoft`

Check for app software updates.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "valid": 1,
  "appVersion": 226,
  "osVersion": 21,
  "updateLevel": 2,
  "appName": "byd",
  "appDesc": "V2.8.0",
  "softType": 0,
  "versionExternal": "2.5.1",
  "url": "https://play.google.com/store/apps/details?id=com.byd.bydautolink",
  "terminalType": 0
}
```

---

### `POST /app/banner/getCountryBannerConfig`

Get banner advertisement configuration for current country.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "bannerImageUrl": "",
  "bannerUrl": "",
  "hasEnabledBanner": "0"
}
```

---

### `POST /common/chargePlatform/operator/queryOperatorList`

Get list of charging platform operators.

**Extra inner fields:** None

**Response `respondData`:**

```json
[
  {
    "dcConnectorCount": 58,
    "apiServerUri": "https://ocpi.tupinrg.dev",
    "locationCount": 40,
    "tokenA": "...",
    "tokenB": "...",
    "tokenC": "...",
    "acConnectorCount": 73,
    "name": "Tupi",
    "evseCount": 138,
    "id": 1,
    "partyId": "TUP",
    "status": 1
  }
]
```

---

### `POST /app/config/getCommonConfig`

**Status:** Error `1005`.

---

### `POST /app/config/getConfigSwitch`

**Status:** Error `1001`.

---

### `POST /app/config/getAllBrandCommonConfig`

**Status:** Error `1005`.

---

### `POST /app/resource/latest`

**Status:** Error `1005`.

---

### `POST /app/banner/getBannerAdList`

**Status:** Error `1001` with empty respondData.

---

### `POST /app/community/getCommunityConfig`

**Status:** Error `1005`.

---

### `POST /app/app-device-log/get-upload-url`

**Status:** Error `1001`.

---

### `POST /app/app-device-log/report-upload-result`

**Status:** Not probed (mutating endpoint).

---

## Agreements & Common

### `POST /common/agreement/getBulletinList`

**Status:** Error `1001`.

---

### `POST /common/agreement/userAgreement`

**Status:** Error `1001`.

---

### `POST /common/agreement/getAppPopUps`

**Status:** Error `1001`.

---

### `POST /common/agreement/updateAgreement`

**Status:** Not probed (mutating endpoint).

---

### `POST /common/agreement/updateAgreementOne`

**Status:** Not probed (mutating endpoint).

---

### `POST /common/basic/getValidateCode`

Send a validation code (SMS/email) for account operations.

**Status:** Error `1001` — requires target phone/email parameters.

---

### `POST /common/basic/validateVerifyData`

Validate a received verification code.

**Status:** Error `1001` — requires code + token parameters.

---

### `POST /common/basic/cancellUser`

Cancel/delete user account.

**Status:** Not probed (mutating/destructive endpoint).

---

---

## Charge Platform

### `POST /common/chargePlatform/operator/location/nearby`

Find nearby charging locations.

**Extra inner fields:** Requires `lat` and `lng` parameters.

**Status:** Error `400291003` — "校验失败:lat:must not be null,lng:must not be null"

**Expected inner fields:**

```json
{
  "lat": "59.123",
  "lng": "10.456"
}
```

---

### `POST /common/chargePlatform/operator/location/search`

Search for a specific charging location.

**Extra inner fields:** Requires `locationId` parameter.

**Status:** Error `400291003` — "校验失败:locationId:must not be null"

---

### `POST /common/chargePlatform/operator/connector/connectorId`

Get connector details by ID.

**Status:** Not probed.

---

### `POST /app/charge/station/bind`

Bind a charging station.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/charge/station/unbind`

Unbind a charging station.

**Status:** Not probed (mutating endpoint).

---

## User Settings & Profile

### `POST /user/other/getUserCareItem`

Get user care/preference items.

**Extra inner fields:** None

**Response `respondData`:**

```json
[
  {"allowCheck": -1, "careItem": "1"},
  {"allowCheck": -1, "careItem": "2"},
  {"allowCheck": -1, "careItem": "3"},
  {"allowCheck": 1, "careItem": "4"}
]
```

---

### `POST /user/other/feedbackWay`

Get feedback contact information.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "way": "eucloudservice@byd.com"
}
```

---

### `POST /user/other/addToken`

Register a push notification token (FCM/APNs).

**Extra inner fields:** Requires `token`/`deviceToken` parameter.

**Status:** Error `1001`.

---

### `POST /user/other/setUserCareItem`

Set user care preferences.

**Status:** Not probed (mutating endpoint).

---

### `POST /user/userInfo/modifyLoginPassword`

Change login password.

**Status:** Not probed (mutating endpoint).

---

### `POST /user/scanlogin/scanLoginByAction`

QR code scan login action.

**Status:** Not probed.

---

### `POST /user/scanlogin/scanLoginByAuth`

QR code scan login auth.

**Status:** Not probed.

---

### `POST /user/scanlogin/scanLoginCancel`

Cancel QR code scan login.

**Status:** Not probed.

---

## Message Center

### `POST /app/messageCenter/getUnReadMessageList`

Get list of unread messages.

**Extra inner fields:** None

**Status:** Error `1010`.

---

### `POST /app/messageCenter/getUnReadMessageOne`

Get a single unread message.

**Extra inner fields:** None

**Status:** Error `1010`.

---

### `POST /app/messageCenter/setToRead`

Mark a message as read.

**Status:** Not probed (mutating endpoint).

---

### `POST /app/messageCenter/deleteMessage`

Delete a message.

**Status:** Not probed (mutating endpoint).

---

## NPS & Feedback

### `POST /nps/apiService/manager/showCondition`

Check if NPS (Net Promoter Score) feedback survey should be shown.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "resultCode": "0",
  "resultDesc": "请重试！",
  "resultData": {
    "isFirst": false,
    "isShow": false
  }
}
```

---

### `POST /nps/apiService/manager/msgRemindCheck`

Check NPS message reminder status.

**Extra inner fields:** None

**Response `respondData`:**

```json
{
  "resultCode": "-1",
  "resultDesc": "Please try again！"
}
```

---

### `POST /nps/apiService/manager/saveQueInfo`

Save NPS questionnaire response.

**Status:** Not probed (mutating endpoint).

---

### `POST /nps/apiService/manager/addWhitelist`

Add user to NPS whitelist.

**Status:** Not probed (mutating endpoint).

---

## Fleet Management (FMS)

FMS endpoints use a separate authentication system. All tested endpoints return outer code `0` but inner response indicates `401` ("账号未登录" — "account not logged in"). FMS likely requires a fleet account or separate login.

### `POST /fms/h5/member/center/indexMessage`

FMS member center index.

**Response `respondData`:**

```json
{
  "code": 401,
  "data": null,
  "msg": "账号未登录"
}
```

---

### `POST /fms/h5/member/center/messagePage`

FMS member message page.

**Response:** Same `401` pattern.

---

### `POST /fms/h5/member/center/readMessage`

Mark FMS message as read.

**Status:** Not probed (mutating endpoint).

---

### `POST /fms/h5/energy/rank/list`

FMS energy consumption ranking.

**Response `respondData`:**

```json
{
  "code": 400,
  "data": null,
  "msg": "请求参数不正确:能耗排名方式不能为空"
}
```

> Translation: "Request parameters incorrect: energy consumption ranking method cannot be empty"

---

### `POST /fms/h5/energy/rank/fleet/list`

FMS energy rank by fleet. **Response:** `401`.

---

### `POST /fms/h5/energy/rank/fleetAndModel/list`

FMS energy rank by fleet and model. **Response:** `401`.

---

### `POST /fms/h5/energy/rank/series/list`

FMS energy rank by series. **Response:** `401`.

---

### `POST /fms/h5/fleet/warn-record/fleet/detail/page`

FMS fleet warning record details. **Response:** `401`.

---

### `POST /fms/h5/fleet/warn-record/fleet/total/page/fms`

FMS fleet warning record totals. **Response:** `401`.

---

## User UI Routes (non-API)

These paths are internal app navigation routes, **not API endpoints**. They appear in the APK because they are used for in-app routing (deep links, webviews).

| Route | Purpose |
|-------|---------|
| `/user/MessageActivity` | Message activity screen |
| `/user/SimCardIdentify` | SIM card identification |
| `/user/about` | About screen |
| `/user/accountCancel` | Account cancellation flow |
| `/user/accountSecurity` | Account security settings |
| `/user/avatarPre` | Avatar preview |
| `/user/changeLoginPwd` | Change password screen |
| `/user/digitalKeyMessage` | Digital key messages |
| `/user/fleetMessage` | Fleet messages |
| `/user/forgotPd` | Forgot password |
| `/user/message` | Messages |
| `/user/messageCentre` | Message center |
| `/user/mineInfoMain` | Profile main screen |
| `/user/othersagreemnets` | Other agreements |
| `/user/personCenter` | Person center |
| `/user/remoteControl` | Remote control screen |
| `/user/scanLoginVehicle` | Scan login vehicle |
| `/user/serviceMessage` | Service messages |
| `/user/setCarAdmin` | Set car admin |
| `/user/setInitPassword` | Set initial password |
| `/user/setting` | Settings screen |
| `/user/systemMessage` | System messages |
| `/user/userCare` | User care preferences |
| `/user/vehicleDetail` | Vehicle detail screen |
| `/user/vehicleMessage` | Vehicle messages |

---

## 404 / Non-existent Endpoints

These endpoints return HTTP 404 and are not available on the current API server:

| Endpoint | Notes |
|----------|-------|
| `/app/model_asset` | Model 3D assets (may be served differently) |
| `/app/splash` | Splash screen config |
| `/app/test` | Test endpoint |
| `/common/authAgreement` | Auth agreement page |
| `/common/sentryAgreement` | Sentry agreement page |
| `/common/shoppingMall` | Shopping mall page |
| `/common/webview` | Webview base |
| `/common/webview/native` | Native webview |
| `/common/webview/native/nps` | NPS webview |
| `/common/webviewNative` | Alt native webview path |
| `/common/webviewNps` | Alt NPS webview path |
| `/control/getRefrigeratorNowOverTime` | Refrigerator overtime |
| `/nfc/all/keys` | All NFC keys (old endpoint) |
| `/nfc/detail` | NFC detail (old endpoint) |
| `/nfc/digitalKey` | NFC digital key (old endpoint) |
| `/nfc/activate` | NFC activate (old endpoint) |
| `/user/verify` | User verification |

> Some of these (webview, agreements) are likely served as static HTML pages rather than API endpoints.

---

## Write-only / Mutating Endpoints (not probed)

These endpoints modify state and were **intentionally not probed** to avoid side effects:

| Endpoint | Purpose |
|----------|---------|
| `/app/account/bind` | Bind social account |
| `/app/account/logout` | Logout session |
| `/app/account/modifyDefaultCar` | Change default vehicle |
| `/app/account/rejectCancellUser` | Reject account cancellation |
| `/app/account/setLoginPassword` | Set login password |
| `/app/account/user/modify` | Modify user profile |
| `/app/charge/station/bind` | Bind charging station |
| `/app/charge/station/unbind` | Unbind charging station |
| `/app/messageCenter/deleteMessage` | Delete message |
| `/app/messageCenter/setToRead` | Mark message as read |
| `/app/rental/vehicle/bind` | Bind rental vehicle |
| `/app/scanWatch/login/action` | Watch login action |
| `/app/scanWatch/login/cancel` | Cancel watch login |
| `/common/agreement/updateAgreement` | Update agreement acceptance |
| `/common/agreement/updateAgreementOne` | Update single agreement |
| `/common/basic/cancellUser` | Cancel/delete user account |
| `/control/bluetooth/activateKey` | Activate Bluetooth key |
| `/control/otaUpgrade/bookingUpgrade` | Schedule OTA upgrade |
| `/control/otaUpgrade/cancelUpgrade` | Cancel OTA upgrade |
| `/control/otaUpgrade/upgradeOta` | Perform OTA upgrade |
| `/control/remoteControl` | Send remote control command |
| `/control/remoteControlBatteryHeat` | Battery heat command |
| `/control/smartCharge/changeChargeStatue` | Start/stop charging |
| `/control/smartCharge/saveOrUpdate` | Save charge schedule |
| `/control/smartCharge/saveOrUpdateJourney` | Save journey charge |
| `/control/standby-vehicles/send` | Send standby command |
| `/external/widget/setControlItem` | Set widget control |
| `/externalControl/remoteControl` | Widget remote control |
| `/nfc/app/v1/c3/changeOwnerDevice` | Change NFC owner |
| `/nfc/app/v1/c3/pairing` | NFC pairing |
| `/nfc/app/v1/c3/pairingpassword` | NFC pairing password |
| `/nfc/app/v1/c3/setUwbFunc` | Set UWB function |
| `/nfc/app/v1/delete` | Delete NFC key |
| `/nps/apiService/manager/saveQueInfo` | Save NPS response |
| `/nps/apiService/manager/addWhitelist` | Add to NPS whitelist |
| `/user/other/setUserCareItem` | Set user care prefs |
| `/user/userInfo/modifyLoginPassword` | Change password |
| `/user/scanlogin/scanLoginByAction` | Scan login action |
| `/user/scanlogin/scanLoginByAuth` | Scan login auth |
| `/user/scanlogin/scanLoginCancel` | Cancel scan login |
| `/vehicle/empower/manage/add` | Add shared user |
| `/vehicle/empower/manage/delete` | Remove shared user |
| `/vehicle/empower/manage/edit` | Edit sharing permissions |
| `/vehicle/usedCar/bindVehicle` | Bind used car |
| `/vehicle/usedCar/transferVehicle` | Transfer vehicle |
| `/vehicle/usedCar/removeVehicle` | Remove vehicle |
| `/vehicle/vehicleswitch/modifyAutoAlias` | Change vehicle alias |
| `/vehicle/vehicleswitch/modifyAutoPlate` | Change license plate |
| `/vehicle/vehicleswitch/modifyControlPassword` | Change control password |
| `/vehicle/vehicleswitch/modifyAllControlPassword` | Change all control passwords |
| `/vehicle/vehicleswitch/setControlPassword` | Set control password |
| `/vehicle/vehicleswitch/setPushSwitchState` | Set push notification |
| `/vehicle/vehicleswitch/setVinSwitchState` | Set VIN switch |
| `/vehicle/vehicleswitch/updatePicColor` | Update vehicle color |
| `/vehicle/vehicleswitch/verifyControlPassword` | Verify control password |
| `/vehicleInfo/auth/unbindByIccid` | Unbind SIM card |
