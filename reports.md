# Fleet Statistics / Trips Report
url:

payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "Trip",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 2
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 7
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:20:00.3529707Z"
}

# Fleet Summary Report
url: api/admin/reports/fleet-summary
payload:
{
    "page": 1,
    "size": 10,
    "assetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7"
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                "assetName": "Fleet",
                "deviceIMEI": "862272084555806",
                "deviceModel": "FMB120",
                "subTenantId": "qa.dev-iot.tracking.me",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me",
                "assetCreatedAt": "2026-01-16T06:43:25.73Z",
                "avlValues": {
                    "_id": "09a3f41d-b863-423f-a7db-b47c6843f254",
                    "created_at": "2026-06-19T13:19:27.191Z",
                    "updated_at": "2026-06-19T13:19:29.377Z",
                    "tenant": "qa.dev-iot.tracking.me",
                    "device_model_id": "codec8",
                    "device_id": "000F383632323732303834353535383036",
                    "imei": "862272084555806",
                    "model": "FMB120",
                    "manufacturer": "Teltonika",
                    "data_protocol": "codec8",
                    "group_id": "980c3d7c-49b4-4f12-a9b6-ee3beddfe0a3",
                    "group_size": 1,
                    "packet_index": 0,
                    "raw_packet": "AAAAAAAAAJ4IAQAAAZ7gB4n4ABdSXzsM34CA/+4ABBMAAAAiC+8A8AAVBUUBAQCzAAIAtABxZFEAUgAMtQAJtgAFQjHXGAAAQw/hRAAACQEDBgEDVABvVQAAWgEAcwHCCPEAAKQTEAAWobpIAAAAAFcH59l4ZAAAL2pnAAANF2kAFmD3awAAB6EDCwAAAAIYPUTaTAAAAAAAAAAADgAAAACXpw8xAQAAMBY=",
                    "received_on": "2026-06-19T13:19:27.181Z",
                    "timestamp": "2026-06-19T13:17:31Z",
                    "priority": 0,
                    "location": {
                        "type": "Point",
                        "coordinates": [
                            21.5974016,
                            39.1274299
                        ]
                    },
                    "altitude": -18,
                    "direction_angle": 4,
                    "satellites": 19,
                    "speed": 0,
                    "ignition_status": "Off",
                    "gsm_signal": "5",
                    "gps_status": "GNSS ON with fix",
                    "digital_input_1": "0",
                    "digital_input_2": "0",
                    "digital_output_1": "0",
                    "digital_output_2": "0",
                    "external_voltage": "12759",
                    "analog_input_1": "259",
                    "total_odometer": "1483194",
                    "dallas_temperature_1": "0",
                    "dallas_temperature_id_1": "0",
                    "vehicle_speed": "0",
                    "accelerator_pedal_position": "0",
                    "fuel_level_litters": "11.100000000000001",
                    "engine_rpm": "0",
                    "engine_temperature": "45",
                    "total_mileage": "132635000",
                    "program_number": "12138",
                    "engine_worktime": "3351",
                    "total_mileage_counted": "1466615",
                    "fuel_consumed_counted": "195.3",
                    "g_sensor": [],
                    "crash_trace": [],
                    "all_io_elements": [
                        {
                            "io_id": "239",
                            "io_value": "0"
                        },
                        {
                            "io_id": "240",
                            "io_value": "0"
                        },
                        {
                            "io_id": "21",
                            "io_value": "5"
                        },
                        {
                            "io_id": "69",
                            "io_value": "1"
                        },
                        {
                            "io_id": "1",
                            "io_value": "0"
                        },
                        {
                            "io_id": "179",
                            "io_value": "0"
                        },
                        {
                            "io_id": "2",
                            "io_value": "0"
                        },
                        {
                            "io_id": "180",
                            "io_value": "0"
                        },
                        {
                            "io_id": "113",
                            "io_value": "100"
                        },
                        {
                            "io_id": "81",
                            "io_value": "0"
                        },
                        {
                            "io_id": "82",
                            "io_value": "0"
                        },
                        {
                            "io_id": "181",
                            "io_value": "9"
                        },
                        {
                            "io_id": "182",
                            "io_value": "5"
                        },
                        {
                            "io_id": "66",
                            "io_value": "12759"
                        },
                        {
                            "io_id": "24",
                            "io_value": "0"
                        },
                        {
                            "io_id": "67",
                            "io_value": "4065"
                        },
                        {
                            "io_id": "68",
                            "io_value": "0"
                        },
                        {
                            "io_id": "9",
                            "io_value": "259"
                        },
                        {
                            "io_id": "6",
                            "io_value": "259"
                        },
                        {
                            "io_id": "84",
                            "io_value": "11.100000000000001"
                        },
                        {
                            "io_id": "85",
                            "io_value": "0"
                        },
                        {
                            "io_id": "90",
                            "io_value": "256"
                        },
                        {
                            "io_id": "115",
                            "io_value": "45"
                        },
                        {
                            "io_id": "241",
                            "io_value": "42003"
                        },
                        {
                            "io_id": "16",
                            "io_value": "1483194"
                        },
                        {
                            "io_id": "72",
                            "io_value": "0"
                        },
                        {
                            "io_id": "87",
                            "io_value": "132635000"
                        },
                        {
                            "io_id": "100",
                            "io_value": "12138"
                        },
                        {
                            "io_id": "103",
                            "io_value": "3351"
                        },
                        {
                            "io_id": "105",
                            "io_value": "1466615"
                        },
                        {
                            "io_id": "107",
                            "io_value": "195.3"
                        },
                        {
                            "io_id": "11",
                            "io_value": "8996603098"
                        },
                        {
                            "io_id": "76",
                            "io_value": "0"
                        },
                        {
                            "io_id": "14",
                            "io_value": "2544308017"
                        }
                    ],
                    "movement": "Off",
                    "iccid": "8996603098",
                    "iccid2": "2544308017",
                    "analog_input_2": "259",
                    "is_processed": true,
                    "processed_at": 639174719693775633,
                    "is_unprocessed": false,
                    "is_wrong": false,
                    "sub_tenant_id": "qa.dev-iot.tracking.me",
                    "device_context": {
                        "serial_number": null,
                        "device_name": "FS 30April",
                        "asset_id": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                        "asset_name": "Fleet",
                        "driver_info": null
                    },
                    "sensors": {
                        "total_odometer_applied": false,
                        "total_odometer": 1483194,
                        "speed_applied": false,
                        "speed": 0,
                        "battery_level_applied": false,
                        "battery_level": 0,
                        "engine_rpm_applied": false,
                        "engine_rpm": 0,
                        "engine_temperature_applied": false,
                        "engine_temperature": 45,
                        "gsm_signal_applied": false,
                        "gsm_signal": 5,
                        "gnss_status_applied": false,
                        "gnss_status": 0,
                        "power_status_applied": false,
                        "power_status": 0,
                        "external_voltage_applied": false,
                        "external_voltage": 12759,
                        "direction_angle_applied": false,
                        "direction_angle": 4,
                        "engine_percent_load_applied": false,
                        "engine_percent_load": 0,
                        "fuel_level_litters_applied": true,
                        "fuel_level_litters": 8.325000000000001,
                        "fuel_level_percentage_applied": false,
                        "fuel_level_percentage": 0,
                        "crash_detection_applied": false,
                        "crash_detection": 0,
                        "weight_value_applied": false,
                        "temperature_value_applied": false,
                        "humidity_value_applied": false,
                        "door_value_applied": false,
                        "weight_value_1_applied": false,
                        "temperature_value_1_applied": false,
                        "humidity_value_1_applied": false,
                        "door_value_1_applied": false,
                        "weight_value_2_applied": false,
                        "temperature_value_2_applied": false,
                        "humidity_value_2_applied": false,
                        "door_value_2_applied": false,
                        "weight_value_3_applied": false,
                        "temperature_value_3_applied": false,
                        "humidity_value_3_applied": false,
                        "door_value_3_applied": false,
                        "weight_value_4_applied": false,
                        "temperature_value_4_applied": false,
                        "humidity_value_4_applied": false,
                        "door_value_4_applied": false
                    },
                    "behaviour": {},
                    "applied_alerts": [],
                    "geofencealert": [],
                    "device_state": {
                        "motion_state": {
                            "_id": "af12ff2d-a548-484a-b1f6-1d01e6fd0fb9",
                            "status": "Stopped",
                            "duration": 82872,
                            "started_at": "2026-06-18T14:16:19Z",
                            "last_updated": "2026-06-19T13:17:31Z"
                        }
                    }
                }
            }
        ],
        "pageNumber": 1,
        "totalPages": 1,
        "totalCount": 1,
        "hasPreviousPage": false,
        "hasNextPage": false
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:21:02.0679697Z"
}

# Fleet Summary Detail Report
URL: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "AssetStatus",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 15
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 60
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 32
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:23:10.0750643Z"
}

# Fleet Performance Summary Report
URL: /api/admin/reports/fleet-performance
payload:
{
    "page": 1,
    "size": 10,
    "startDate": "2026-06-16T00:00:00",
    "endDate": "2026-06-23T23:59:59",
    "assetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7"
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                "assetName": "Fleet",
                "distanceTravelled": 118651,
                "totalTrips": 14,
                "avgTripDuration": 1142.71,
                "totalIdleTime": 4080,
                "fuelUsed": 11.4,
                "alertsTriggered": 1462,
                "downTime": 0,
                "subTenantId": "qa.dev-iot.tracking.me",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            }
        ],
        "pageNumber": 1,
        "totalPages": 1,
        "totalCount": 1,
        "hasPreviousPage": false,
        "hasNextPage": false
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:24:28.0579086Z"
}


# Fuel Summary Report
url:/api/admin/reports/fuel-summary-v1

payload:
{
    "page": 1,
    "size": 10,
    "startDate": "2026-06-15T19:00:00.000Z",
    "endDate": "2026-06-23T18:59:59.000Z",
    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7"
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                "assetName": "Fleet",
                "subTenantId": "",
                "subTenantName": "",
                "totalTime": 192,
                "initialFuelLevel": 19.73,
                "finalFuelLevel": 8.33,
                "fuelFillings": 0,
                "totalFuelRefilled": 0,
                "fuelDrainCount": 0,
                "fuelDrainAmount": 0,
                "fuelConsumedLitres": 11.4,
                "distanceCovered": 118.88,
                "mileagePerLitre": 10.43,
                "startLocation": "21.5974033,39.127435",
                "endLocation": "21.5974016,39.1274299",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            }
        ],
        "pageNumber": 1,
        "totalPages": 1,
        "totalCount": 1,
        "hasPreviousPage": false,
        "hasNextPage": false
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:26:22.5773103Z"
}


# SIM Report
url: /api/admin/reports/sim
payload:
{
    "page": 1,
    "size": 10,
    "startDate": "2026-06-15T19:00:00.000Z",
    "endDate": "2026-06-23T18:59:59.000Z",
    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7"
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "assetName": "Fleet",
                "assetType": "",
                "plateNo": "3688 JVR",
                "accountName": "",
                "deviceName": "FS 30April",
                "imei": "862272084555806",
                "simNo": "Sim Not Assigned",
                "driverName": "",
                "installationtype": "Basic",
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me",
                "installDate": null,
                "expiryDate": null,
                "createdAt": null
            }
        ],
        "pageNumber": 1,
        "totalPages": 1,
        "totalCount": 1,
        "hasPreviousPage": false,
        "hasNextPage": false
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:27:01.159403Z"
}

# Fuel Trip Consumption Report
url: /api/admin/reports/fetch-dates
paylaod:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "FuelConsumption",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 2
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 7
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:27:45.9198753Z"
}

# Odometer Report
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "Odometer",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 2
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 7
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:28:26.7853172Z"
}

# Utilization Report/Work Hour Report
url: /api/admin/reports/utilization
payloadd:
{
    "page": 1,
    "size": 10,
    "startDate": "2026-06-15T19:00:00.000Z",
    "endDate": "2026-06-23T18:59:59.000Z"
}
response:
{
    "success": true,
    "data": {
        "items": [],
        "pageNumber": 1,
        "totalPages": 0,
        "totalCount": 0,
        "hasPreviousPage": false,
        "hasNextPage": false
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:29:13.0487242Z"
}

# Duty Hour Report
url: /api/admin/reports/duty-hour
payload:
{
    "page": 1,
    "size": 10,
    "timeZone": "Asia/Karachi",
    "startDate": "2026-06-16T05:00:00.000Z",
    "endDate": "2026-06-23T14:00:00.000Z",
    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7"
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "id": "d4e3cc4e-0f46-46dc-8765-8fda589c8e37",
                "startAt": "2026-06-16T07:44:16Z",
                "endAt": "2026-06-16T07:54:33Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.597285,
                        39.1274333
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5811749,
                        39.1606166
                    ]
                },
                "distanceCovered": 5.23,
                "avgSpeed": 29,
                "maxSpeed": 61,
                "idleTime": 0,
                "duration": 10.28,
                "inMotionDuration": 10.28,
                "durationBetweenTrips": 0,
                "startOdometer": 1364.32,
                "endOdometer": 1369.55,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "7ce12f47-7aeb-4c01-b61d-77615fc3b4cd",
                "startAt": "2026-06-16T08:59:34Z",
                "endAt": "2026-06-16T09:26:52Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5812566,
                        39.1606766
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5972916,
                        39.1276016
                    ]
                },
                "distanceCovered": 7.62,
                "avgSpeed": 37,
                "maxSpeed": 71,
                "idleTime": 13,
                "duration": 27.3,
                "inMotionDuration": 14.3,
                "durationBetweenTrips": 65.02,
                "startOdometer": 1369.56,
                "endOdometer": 1377.18,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "e1075ff4-c234-49f4-9db6-c8a704b3829f",
                "startAt": "2026-06-17T07:43:26Z",
                "endAt": "2026-06-17T08:02:16Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5972666,
                        39.1274566
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5813416,
                        39.160635
                    ]
                },
                "distanceCovered": 6.54,
                "avgSpeed": 27,
                "maxSpeed": 63,
                "idleTime": 5,
                "duration": 18.83,
                "inMotionDuration": 13.83,
                "durationBetweenTrips": 1336.57,
                "startOdometer": 1377.24,
                "endOdometer": 1383.79,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "5ef2d36e-cbaf-4c8c-b8cd-0d7729b3ff94",
                "startAt": "2026-06-17T09:05:44Z",
                "endAt": "2026-06-17T09:11:10Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5813516,
                        39.1606233
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5881583,
                        39.157385
                    ]
                },
                "distanceCovered": 1.59,
                "avgSpeed": 24,
                "maxSpeed": 48,
                "idleTime": 2,
                "duration": 5.43,
                "inMotionDuration": 3.43,
                "durationBetweenTrips": 63.47,
                "startOdometer": 1383.8,
                "endOdometer": 1385.39,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "f7cee749-b944-4028-bdc2-4d0326519304",
                "startAt": "2026-06-17T09:14:11Z",
                "endAt": "2026-06-17T09:39:05Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5881616,
                        39.1572733
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5972866,
                        39.127615
                    ]
                },
                "distanceCovered": 6.86,
                "avgSpeed": 27,
                "maxSpeed": 65,
                "idleTime": 11,
                "duration": 24.9,
                "inMotionDuration": 13.9,
                "durationBetweenTrips": 3.02,
                "startOdometer": 1385.41,
                "endOdometer": 1392.27,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "cd150789-babe-4d03-b18a-9afa972e0ffc",
                "startAt": "2026-06-17T11:52:54Z",
                "endAt": "2026-06-17T12:58:31Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5972783,
                        39.1276583
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.4893716,
                        39.173845
                    ]
                },
                "distanceCovered": 44.95,
                "avgSpeed": 44,
                "maxSpeed": 90,
                "idleTime": 9,
                "duration": 65.62,
                "inMotionDuration": 56.62,
                "durationBetweenTrips": 133.82,
                "startOdometer": 1392.28,
                "endOdometer": 1437.23,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "37542ef7-527b-44a3-b294-9262fbb47d97",
                "startAt": "2026-06-17T13:41:28Z",
                "endAt": "2026-06-17T14:18:14Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.4893933,
                        39.1737866
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5974216,
                        39.1274166
                    ]
                },
                "distanceCovered": 18.42,
                "avgSpeed": 36,
                "maxSpeed": 95,
                "idleTime": 1,
                "duration": 36.77,
                "inMotionDuration": 35.77,
                "durationBetweenTrips": 42.95,
                "startOdometer": 1437.23,
                "endOdometer": 1455.65,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "7a0ac817-d3d8-4c6c-87dd-4e317e1a9e29",
                "startAt": "2026-06-18T06:57:48Z",
                "endAt": "2026-06-18T07:04:52Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5972583,
                        39.1274633
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.6090699,
                        39.1317033
                    ]
                },
                "distanceCovered": 4.63,
                "avgSpeed": 35,
                "maxSpeed": 69,
                "idleTime": 0,
                "duration": 7.07,
                "inMotionDuration": 7.07,
                "durationBetweenTrips": 999.57,
                "startOdometer": 1455.66,
                "endOdometer": 1460.3,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "0b949b31-42b5-4c6c-a5de-816035b45f72",
                "startAt": "2026-06-18T07:27:31Z",
                "endAt": "2026-06-18T07:33:33Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.6090466,
                        39.131765
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5973816,
                        39.1277433
                    ]
                },
                "distanceCovered": 2.68,
                "avgSpeed": 25,
                "maxSpeed": 55,
                "idleTime": 0,
                "duration": 6.03,
                "inMotionDuration": 6.03,
                "durationBetweenTrips": 22.65,
                "startOdometer": 1460.3,
                "endOdometer": 1462.97,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            },
            {
                "id": "f6fea163-adf2-4f70-a649-0185ceb79ba2",
                "startAt": "2026-06-18T07:36:38Z",
                "endAt": "2026-06-18T07:48:41Z",
                "startLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5974216,
                        39.1277516
                    ]
                },
                "endLocation": {
                    "type": "Point",
                    "coordinates": [
                        21.5784133,
                        39.1569616
                    ]
                },
                "distanceCovered": 5.62,
                "avgSpeed": 31,
                "maxSpeed": 74,
                "idleTime": 1,
                "duration": 12.05,
                "inMotionDuration": 11.05,
                "durationBetweenTrips": 3.08,
                "startOdometer": 1462.97,
                "endOdometer": 1468.59,
                "reportDriverInfo": {
                    "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
                    "assetName": "Fleet"
                },
                "subTenantId": "",
                "customerName": "qa",
                "customerId": "qa.dev-iot.tracking.me"
            }
        ],
        "pageNumber": 1,
        "totalPages": 2,
        "totalCount": 14,
        "hasPreviousPage": false,
        "hasNextPage": true
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:30:18.8595424Z"
}

# Stop Time Report
url: /api/admin/reports/fetch-dates
payload: {
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "StopTime",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 3
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 8
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:32:50.3126738Z"
}

# Idle Time Report
url: /api/admin/reports/fetch-dates
payload: 
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "Idling",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 3
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 13
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 5
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:33:30.7540007Z"
}

# Idling - Keyrent Report
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
    "Type": "Idling",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "d3aadd6b-d10d-4522-9370-a2e09e2cb9f7",
            "assetName": "Fleet",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 3
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 13
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 5
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:34:21.3302765Z"
}

# Geofence Report In
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "Type": "Geofence",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "55c25f9d-d95c-46bb-ba70-09aeed860005",
            "assetName": "6382 RTB",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-17T00:00:00Z",
                    "count": 4
                },
                {
                    "date": "2026-06-18T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-21T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-22T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-23T00:00:00Z",
                    "count": 2
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:36:13.503546Z"
}

# Geofence Report Out
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "Type": "GeofenceOut",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "55c25f9d-d95c-46bb-ba70-09aeed860005",
            "assetName": "6382 RTB",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-17T00:00:00Z",
                    "count": 4
                },
                {
                    "date": "2026-06-18T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-21T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-22T00:00:00Z",
                    "count": 1
                },
                {
                    "date": "2026-06-23T00:00:00Z",
                    "count": 2
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:37:02.038181Z"
}

# Track Data Report/All Parameters
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "Type": "RawTrackData",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "55c25f9d-d95c-46bb-ba70-09aeed860005",
            "assetName": "6382 RTB",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 409
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 2146
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 1035
                },
                {
                    "date": "2026-06-19T00:00:00",
                    "count": 48
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 379
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 978
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 615
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 1198
                }
            ]
        },
        {
            "assetId": "fb3551f3-fe65-417f-a70e-10ba43a259c4",
            "assetName": "9293 AGR",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 2153
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 1215
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 1128
                },
                {
                    "date": "2026-06-19T00:00:00",
                    "count": 24
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 42
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 1030
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 2782
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 658
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:38:03.1627143Z"
}

# Over Speeding Report
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "Type": "Overspeeding",
    "timeZone": "Asia/Karachi"
}

response: 
{
    "success": true,
    "data": [
        {
            "assetId": "55c25f9d-d95c-46bb-ba70-09aeed860005",
            "assetName": "6382 RTB",
            "dateRecords": [
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 2
                }
            ]
        },
        {
            "assetId": "fb3551f3-fe65-417f-a70e-10ba43a259c4",
            "assetName": "9293 AGR",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 25
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 6
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 13
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:38:46.9979377Z"
}

# Over speeding - Keyrent Report
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "4bda3301-3001-460a-bd04-5b148917f96a,4324fd68-caeb-49a5-b6da-4db0cc650e0f,303edec0-ebcb-4f00-9a38-c96fc9c74717,ca447616-122a-4cbf-aa45-d09addc73064",
    "Type": "Overspeeding",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "303edec0-ebcb-4f00-9a38-c96fc9c74717",
            "assetName": "8088 VRA",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 272
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 266
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 233
                },
                {
                    "date": "2026-06-19T00:00:00",
                    "count": 19
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 111
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 287
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 425
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 190
                }
            ]
        },
        {
            "assetId": "4bda3301-3001-460a-bd04-5b148917f96a",
            "assetName": "1136 DSA",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 341
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 535
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 595
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 381
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 603
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 451
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 1265
                }
            ]
        },
        {
            "assetId": "ca447616-122a-4cbf-aa45-d09addc73064",
            "assetName": "2818 ASA",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 138
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 153
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 190
                },
                {
                    "date": "2026-06-19T00:00:00",
                    "count": 29
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 71
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 106
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 100
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 96
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:56:25.9795248Z"
}


# Driving Behaviour Report
url: /api/admin/reports/fetch-dates
paylaod:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "8aaf64b6-f2b7-4f0c-93d6-6c29635cb48b,16598c8f-51d9-439d-b2ab-27ba3cd5ae9b",
    "Type": "DriverBehavior",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "16598c8f-51d9-439d-b2ab-27ba3cd5ae9b",
            "assetName": "ObaidAllah Ghayyas",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 1
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 33
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 3
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 6
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 12
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 22
                }
            ]
        },
        {
            "assetId": "8aaf64b6-f2b7-4f0c-93d6-6c29635cb48b",
            "assetName": "Abdulaziz Mohammad",
            "dateRecords": [
                {
                    "date": "2026-06-15T00:00:00",
                    "count": 12
                },
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 42
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 12
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 48
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 31
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 162
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 13
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:39:30.8649539Z"
}

# Events Report
url: /api/admin/reports/fetch-dates

payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "Type": "Event",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "55c25f9d-d95c-46bb-ba70-09aeed860005",
            "assetName": "6382 RTB",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 1
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 33
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 5
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 3
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 6
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 12
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 22
                }
            ]
        },
        {
            "assetId": "fb3551f3-fe65-417f-a70e-10ba43a259c4",
            "assetName": "9293 AGR",
            "dateRecords": [
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 54
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 12
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 48
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 31
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 162
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 13
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:41:22.2032772Z"
}

# User Alert History Report
url: /api/admin/reports/alerts-history

payload:
{
    "startDate": "2026-06-15T19:00:00.000Z",
    "endDate": "2026-06-23T18:59:59.999Z",
    "assetIds": "55c25f9d-d95c-46bb-ba70-09aeed860005,fb3551f3-fe65-417f-a70e-10ba43a259c4",
    "page": 1,
    "size": 10
}

response:
{
    "success": true,
    "data": {
        "items": [
            {
                "id": "a55798fb-7fb7-4da8-be00-d5385bad7257",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 In",
                "createdAt": "2026-06-16T07:53:30Z"
            },
            {
                "id": "010826ce-376d-41f2-a7eb-1be97dd6a354",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 Out",
                "createdAt": "2026-06-16T09:04:08Z"
            },
            {
                "id": "3db2920e-16ca-4e44-bb9b-7a36ec2564b2",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 In",
                "createdAt": "2026-06-17T07:58:55Z"
            },
            {
                "id": "b2d97ed4-75eb-48e9-b3c5-c69c340da157",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 Out",
                "createdAt": "2026-06-17T09:06:26Z"
            },
            {
                "id": "221fcb92-c852-48c4-b4a8-7e42d6ed5e45",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 In",
                "createdAt": "2026-06-17T12:01:29Z"
            },
            {
                "id": "511fca50-2232-4c2a-b39c-4cdc167a2b51",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 Out",
                "createdAt": "2026-06-17T12:11:01Z"
            },
            {
                "id": "2748da2c-8cba-4c42-b6ec-3b25ae0bbf44",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 In",
                "createdAt": "2026-06-17T12:11:48Z"
            },
            {
                "id": "41d8e02e-978d-40e9-a2a3-650ff5ac315c",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 Out",
                "createdAt": "2026-06-17T12:15:24Z"
            },
            {
                "id": "bc888c95-33e1-4a9a-89ea-1d2af84758fb",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 In",
                "createdAt": "2026-06-17T13:51:51Z"
            },
            {
                "id": "a54c5055-a65b-4e0d-b01a-b5f8420b3005",
                "severity": "Critical",
                "assetName": "6382 RTB",
                "alertMessage": "Project 1 Out",
                "createdAt": "2026-06-17T13:58:59Z"
            }
        ],
        "pageNumber": 1,
        "totalPages": 2,
        "totalCount": 20,
        "hasPreviousPage": false,
        "hasNextPage": true
    },
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:42:10.7606907Z"
}


# WASL Report
url: /api/admin/reports/fetch-dates
payload:
{
    "StartDate": "2026-06-15T19:00:00.000Z",
    "EndDate": "2026-06-23T18:59:59.999Z",
    "AssetIds": "357073294187907,357073294187824,350612073856989,350612073765883,354017115304517,350612073853911,33912693,357073294578519,350612073694653,350612073694752,350612073766063,350612073694604,350612073694646",
    "Type": "Wasl",
    "timeZone": "Asia/Karachi"
}

response:
{
    "success": true,
    "data": [
        {
            "assetId": "350612073694653",
            "assetName": "1995 ا ر ن",
            "dateRecords": [
                {
                    "date": "2026-06-15T00:00:00",
                    "count": 13
                },
                {
                    "date": "2026-06-16T00:00:00",
                    "count": 497
                },
                {
                    "date": "2026-06-17T00:00:00",
                    "count": 2977
                },
                {
                    "date": "2026-06-18T00:00:00",
                    "count": 1155
                },
                {
                    "date": "2026-06-19T00:00:00",
                    "count": 1601
                },
                {
                    "date": "2026-06-20T00:00:00",
                    "count": 2151
                },
                {
                    "date": "2026-06-21T00:00:00",
                    "count": 2313
                },
                {
                    "date": "2026-06-22T00:00:00",
                    "count": 1462
                },
                {
                    "date": "2026-06-23T00:00:00",
                    "count": 1485
                }
            ]
        }
    ],
    "message": null,
    "errors": [],
    "timestamp": "2026-06-23T10:44:50.8236413Z"
}

