# Collection Index for RAG Retrieval
# Fleet Management System - Collection Chunk Mapping Guide
# This document maps user questions to appropriate collection chunks for retrieval

---

## AlertHistory_base

**Description:** Contains historical records of alerts and notifications triggered in the fleet management system. Includes alert severity (critical, high, medium, low), status (active, resolved, acknowledged), priority, location coordinates (latitude, longitude), timestamps (created, escalated, resolved), and resolution information. Linked to specific assets and drivers. This collection contains: (1) All geofence events/notifications that were triggered (geofence entry, geofence exit, geofence violations); (2) Logs/notifications for AlertRule triggers (when AlertRule rules are fired). Note: Geofence rules/definitions are stored in Geofence_base, but geofence events/notifications are stored here. AlertRule rules/definitions are stored in AlertRule_base, but AlertRule trigger logs/notifications are stored here. SystemAlertRule logs/notifications are stored in Events_base, not here.

**Use for questions about:**
- Alert history and past incidents
- When alerts occurred (timestamps)
- Where alerts happened (locations)
- Alert severity levels
- Alert resolution status
- Alert patterns over time
- Historical alert analysis
- Alert trends and frequency
- Alert investigation
- Geofence events triggered
- Geofence notifications
- Geofence entry/exit events
- Geofence violations
- When geofence events occurred
- Where geofence events happened
- AlertRule trigger logs/notifications

**Key Keywords:** alert history, past alerts, alert records, alert incidents, alert timeline, alert resolution, alert status, alert severity, geofence events, geofence notifications, geofence triggers, geofence entry, geofence exit, geofence violations, AlertRule notifications, AlertRule logs

---

## AlertRule_base

**Description:** Contains fundamental configuration and basic information for alert rules (rules/definitions only). Includes rule name, description, severity level (critical, high, medium, low), enable/disable status, and core alert rule settings. Note: This collection contains only AlertRule rules and definitions. The logs/notifications for when AlertRule triggers are fired are stored in AlertHistory_base collection, not here.

**Use for questions about:**
- Alert rule definitions
- Alert rule names and descriptions
- Alert rule status (enabled/disabled)
- Alert rule configuration
- What alert rules exist
- Alert rule management

**Key Keywords:** alert rule, alert configuration, rule definition, rule settings, alert rule name, rule status

---

## AlertRule_assigned_assets

**Description:** Manages relationships between alert rules and specific vehicles/assets they monitor. Contains vehicle IDs assigned to each rule, asset groups, individual vehicle associations, and assignment status.

**Use for questions about:**
- Which vehicles are monitored by alert rules
- Asset-rule assignments
- Rule coverage for specific vehicles
- Vehicles associated with alert rules
- Asset groups for alert rules

**Key Keywords:** alert rule assignment, monitored vehicles, rule coverage, asset-rule relationship, assigned assets to rules

---

## AlertRule_condition

**Description:** Defines monitoring conditions and trigger criteria for alert rules. Includes value-based conditions (speed thresholds, fuel levels), event-based conditions (geofence entry/exit, ignition changes), threshold values, trigger conditions, and monitoring parameters.

**Use for questions about:**
- How alerts are triggered
- Alert rule conditions
- Alert thresholds (speed, fuel, etc.)
- Alert trigger criteria
- Monitoring conditions
- Alert rule logic

**Key Keywords:** alert condition, trigger criteria, alert threshold, monitoring condition, rule logic, alert trigger

---

## AlertRule_notifications

**Description:** Contains notification settings and recipient configurations for alert rules. Includes email recipients, SMS phone numbers, notification channels (email, SMS, push, in-app), delivery settings, frequency, escalation rules, and preferences.

**Use for questions about:**
- Who receives alerts
- Alert notification settings
- Email/SMS recipients for alerts
- Notification channels
- Alert delivery configuration
- Notification preferences

**Key Keywords:** alert notification, notification recipients, alert email, alert SMS, notification settings, alert delivery

---

## AlertRule_schedule

**Description:** Manages temporal aspects of alert rule monitoring. Defines active hours, monitoring periods, time zones, schedules (days of week, dates), and when rules are active.

**Use for questions about:**
- When alert rules are active
- Alert rule schedules
- Monitoring hours
- Time-based alert rules
- Rule activation periods

**Key Keywords:** alert schedule, monitoring hours, active times, rule schedule, time-based alerts

---

## AlertRule_trigger

**Description:** Controls execution and frequency parameters for alert rule triggering. Includes trigger frequency, cooldown periods, execution settings, and parameters that prevent alert spam.

**Use for questions about:**
- Alert trigger frequency
- Alert cooldown periods
- Alert rule execution
- Preventing alert spam
- Alert frequency settings

**Key Keywords:** trigger frequency, cooldown period, alert execution, alert frequency, alert spam prevention

---

## asset_base

**Description:** Contains fundamental identity and operational state information for each fleet asset. Includes asset_id, name, type (fleet vehicle, equipment), availability status (available, assigned, maintenance, retired), device availability, category, sequence number, installation type, assigned devices/users, operational status (active, inactive, suspended), sub-tenant ID, and creation timestamps.

**Use for questions about:**
- Asset identification
- Asset names and IDs
- Asset types and categories
- Asset availability status
- Asset operational status
- Basic asset information
- Asset lookup

**Key Keywords:** asset, vehicle, fleet vehicle, asset name, asset ID, asset status, asset type, asset availability

---

## asset_details_base

**Description:** Stores essential vehicle identification and specification details. Includes plate number, plate type, vehicle type (car, truck, reefer), fleet type (owned, leased, rented), make/model/variant, manufacturing year, chassis number, vehicle category (light, medium, heavy), VIN, fuel type, transmission type, odometer reading, engine number, tire size, fuel consumption rate, tank capacity, and color.

**Use for questions about:**
- Vehicle identification (plate number, VIN)
- Vehicle specifications (make, model, year)
- Vehicle type and category
- Vehicle characteristics
- Finding vehicles by plate/VIN
- Vehicle details
- Vehicle specifications

**Key Keywords:** plate number, VIN, vehicle specs, make model, vehicle details, vehicle identification, chassis number, odometer

---

## asset_details_cargo_load_management

**Description:** Manages cargo handling, load capacity, and specialized transport requirements. Includes cargo type authorization, maximum permitted load capacity, average load utilization, reefer temperature range settings, cargo inspection dates, and cargo insurance policy information.

**Use for questions about:**
- Cargo capacity
- Load management
- Cargo type authorization
- Reefer temperature settings
- Cargo inspection
- Load utilization
- Cargo insurance

**Key Keywords:** cargo, load capacity, cargo management, reefer temperature, cargo inspection, load utilization, cargo authorization

---

## asset_details_cost_finance

**Description:** Tracks financial aspects and cost-related information. Includes purchase price/date, lease terms/payments, depreciation value, fuel card details, fuel costs, insurance policy information, warranty dates, toll payment accounts, and NFC tag information.

**Use for questions about:**
- Vehicle costs and pricing
- Purchase information
- Lease details
- Insurance policies
- Fuel costs
- Financial information
- Cost tracking
- Warranty information

**Key Keywords:** cost, finance, purchase price, lease, insurance, fuel card, warranty, depreciation, financial

---

## asset_details_custom_optional

**Description:** Contains business-specific and region-specific custom fields. Includes WASL keys (Saudi Arabia), company identity numbers, device IMEI, empty weight, weight factor, TGA activity, category/type specifications, Naqeba license, environmental compliance, tamper-proof seals, customs barcode, Hajj/Umrah permits, and transport ministry licenses.

**Use for questions about:**
- Regional compliance (Saudi Arabia WASL)
- Custom business fields
- Regulatory licenses
- Special permits (Hajj, Umrah)
- Regional compliance requirements
- Custom asset fields

**Key Keywords:** WASL, custom fields, regional compliance, TGA, Naqeba license, Hajj permit, Umrah permit, customs

---

## asset_details_document_status_flags

**Description:** Tracks status and expiration of critical documents required for vehicle operation. Includes document status flags, expiry dates for permits, insurance, registration, regulatory certifications, and compliance monitoring information.

**Use for questions about:**
- Document expiration
- Document status
- Compliance monitoring
- Permit expiration
- Registration status
- Insurance expiration
- Document validity

**Key Keywords:** document status, expiration, expiry date, permit expiration, compliance, document validity, registration status

---

## asset_details_maintenance_logs

**Description:** Maintains maintenance and service history. Includes last service date, next service due date, maintenance schedule, last tyre change date, next tyre change due date, and tyre change schedule.

**Use for questions about:**
- Maintenance history
- Service dates
- Maintenance schedule
- Tyre replacement
- Maintenance due dates
- Service records

**Key Keywords:** maintenance, service history, service date, maintenance schedule, tyre change, maintenance logs

---

## asset_details_ownership_operations

**Description:** Contains ownership structure, business unit assignments, and operational context. Includes ownership information, operational assignments, business unit relationships, and organizational structure.

**Use for questions about:**
- Asset ownership
- Business unit assignments
- Organizational structure
- Ownership information
- Operational context

**Key Keywords:** ownership, business unit, operational assignment, organizational structure

---

## asset_details_safety_security

**Description:** Tracks safety equipment and security features. Includes fire extinguisher status/inspection dates, first aid kit availability/expiration, dashcam installation/status, and other safety equipment status.

**Use for questions about:**
- Safety equipment
- Security features
- Fire extinguisher status
- First aid kit
- Dashcam installation
- Safety compliance
- Safety equipment inspection

**Key Keywords:** safety equipment, security, fire extinguisher, first aid kit, dashcam, safety compliance

---

## asset_details_special_equipment

**Description:** Manages specialized equipment and custom installations. Includes refrigeration unit details, specialized equipment specifications (hydraulic lifts, cranes, custom body modifications), and custom installation information.

**Use for questions about:**
- Specialized equipment
- Refrigeration units
- Custom installations
- Equipment modifications
- Special vehicle equipment

**Key Keywords:** special equipment, refrigeration unit, custom equipment, vehicle modifications, specialized equipment

---

## asset_details_vehicle_capacity_specialization

**Description:** Contains detailed capacity and physical specifications. Includes fleet capacity (tons), pallet capacity, body manufacturer, outer dimensions (length, width, height), inner dimensions, number of axles, axle load specifications, number of doors, and tail lift presence.

**Use for questions about:**
- Vehicle capacity
- Physical dimensions
- Load capacity (tons, pallets)
- Vehicle size
- Axle information
- Capacity planning
- Dimensions

**Key Keywords:** capacity, dimensions, load capacity, fleet capacity, pallet capacity, vehicle size, axles

---

## asset_device_details

**Description:** Links tracking devices to specific assets. Includes IMEI numbers, group ID/name, device name, and device specifications. Establishes asset-device relationships.

**Use for questions about:**
- Device assignments to assets
- Asset-device relationships
- Device IMEI for assets
- Which device tracks which asset
- Device association

**Key Keywords:** device assignment, asset device, IMEI, device relationship, tracking device assignment

---

## AvlRecord_base

**Description:** Contains both LIVE REAL-TIME location data and HISTORICAL GPS tracking data with telemetry from vehicle tracking devices. This collection stores comprehensive location information at every recorded timestamp, providing both current vehicle positions and complete location history over time. Includes precise location coordinates (latitude, longitude in GeoJSON Point format), timestamp indicating when the location was recorded, speed measurements, direction angle showing heading/bearing, altitude measurements, satellite count indicating GPS fix quality, ignition status (On/Off) showing whether the vehicle engine is running, GSM signal strength indicating cellular connectivity, GPS status (GNSS ON with fix/no fix), external voltage measurements, total odometer reading showing cumulative distance, movement status (On/Off) indicating whether vehicle is currently moving or stationary, device identification (device_id, IMEI, model, manufacturer), data protocol information, and associated asset/driver context. Each record represents a point-in-time snapshot of the vehicle's location and status, enabling both real-time monitoring and historical analysis of vehicle movements.

**Use for questions about:**
- Current live location of vehicles (real-time position)
- Historical vehicle locations (where vehicles were at specific times)
- Vehicle location tracking over time periods
- Real-time GPS tracking data
- Historical GPS tracking data
- Vehicle movement patterns and routes
- Location history for specific vehicles
- Current vehicle position (live tracking)
- Where a vehicle is right now
- Where a vehicle was at a specific time
- Speed and direction at any point in time
- Ignition status (current and historical)
- Odometer readings (current and historical)
- Vehicle movement status (moving or stationary)

**Key Keywords:** location, GPS, tracking, position, coordinates, real-time location, live location, current location, historical location, location history, vehicle location, vehicle position, movement, speed, ignition, real-time tracking, GPS history, location tracking

---

## AvlRecord_sensor

**Description:** Extends GPS data with detailed sensor readings and telemetry. Includes high-precision odometer readings, battery voltage, engine RPM, temperature sensor readings, GSM signal strength, G-sensor data (acceleration, deceleration, impact detection), crash trace information, and vehicle sensor measurements from diagnostic systems.

**Use for questions about:**
- Sensor readings
- Engine RPM
- Temperature sensors
- Battery voltage
- G-sensor data
- Crash detection
- Vehicle telemetry
- Sensor measurements

**Key Keywords:** sensor, telemetry, RPM, battery voltage, temperature sensor, G-sensor, crash detection, engine data

---

## DailyAnalytics_base

**Description:** Contains aggregated daily performance metrics and behavioral data. Each DailyAnalytics_base record represents one day's aggregated statistics for an asset or driver, including total distance, fuel consumption, driving behavior scores, safety metrics (harsh braking, acceleration violations, speeding, etc.), operational efficiency indicators, and productivity measures.

**Use for questions about:**
- Daily performance metrics
- Daily statistics
- Daily behavior scores
- Daily safety metrics
- Daily fuel consumption
- Distance covered
- Day-to-day performance
- Daily reports

**Key Keywords:** daily analytics, daily performance, daily statistics, daily metrics, daily report, daily behavior, Distance

---

## Device_base

**Description:** Manages comprehensive information about tracking devices, sensors, and hardware. Includes device specifications (model, manufacturer, capabilities), configuration settings, firmware version, operational status, installation details, warranty information, device health monitoring, device identification (IMEI, device_id), group associations, and metadata.

**Use for questions about:**
- Device information
- Device specifications
- Device configuration
- Firmware version
- Device status
- Device installation
- Device management
- Device health
- Which device
- Which device tracks which asset
- Device installed

**Key Keywords:** device, tracking device, device specs, firmware, device configuration, device status, IMEI, device management, teltonika, altelematics

---

## Driver_base

**Description:** Contains fundamental identity and core identification information for drivers and personnel. Includes unique driver_id, driver name, basic profile information, creation timestamps, and sub-tenant identification.

**Use for questions about:**
- Driver identification
- Driver names
- Driver IDs
- Basic driver information
- Driver lookup

**Key Keywords:** driver, driver name, driver ID, driver identification

---

## Driver_address_contact

**Description:** Stores contact information and communication details. Includes email addresses, phone numbers (mobile, work, home), complete home addresses (street, city, state, postal code), emergency contact information (names, relationships, phone numbers), and communication-related details.

**Use for questions about:**
- Driver contact information
- Driver email
- Driver phone number
- Driver address
- Emergency contacts
- Contact details
- Communication information

**Key Keywords:** contact, email, phone number, address, emergency contact, communication

---

## Driver_asset_assignments

**Description:** Manages relationships between drivers and vehicles they are assigned to operate. Includes assignment history (past/current), assigned vehicle IDs/names, assignment start/end dates, assignment status (active, completed, transferred), assignment type, priority levels, assignment notes, assigned by information, responsibilities, access levels, notification preferences, and schedule information.

**Use for questions about:**
- Which driver is assigned to which vehicle
- Driver-vehicle assignments
- Assignment history
- Current assignments
- Assignment status
- Driver-vehicle relationships

**Key Keywords:** driver assignment, vehicle assignment, assigned driver, driver-vehicle relationship, assignment history

---

## Driver_behavior

**Description:** Contains driving behavior analysis and risk assessment data. Includes risk profile assessments, stress level indicators, compliance scores, harsh braking incident counts/details, harsh acceleration patterns/violations, cornering behavior analysis, speeding incident tracking, behavioral metrics, and safety compliance indicators.

**Use for questions about:**
- Driving behavior
- Behavior analysis
- Harsh braking
- Harsh acceleration
- Speeding incidents
- Risk profile
- Behavior scores
- Safety compliance

**Key Keywords:** behavior, driving behavior, harsh braking, harsh acceleration, speeding, risk profile, behavior analysis

---

## Driver_compliance

**Description:** Tracks regulatory compliance, background checks, and violation history. Includes background check information/results, drug test results/dates, violation history (traffic violations, policy violations), compliance status indicators, regulatory compliance records, certification tracking, and documentation for driver qualification.

**Use for questions about:**
- Driver compliance
- Background checks
- Drug test results
- Violation history
- Compliance status
- Regulatory compliance
- Certification

**Key Keywords:** compliance, background check, drug test, violation history, compliance status, certification

---

## Driver_analytics

**Description:** Contains additional advanced driver performance metrics and behavioral analysis beyond basic analytics. Includes detailed performance breakdowns, advanced behavioral metrics, sophisticated analytics calculations, and in-depth performance tracking data.

**Use for questions about:**
- Advanced driver analytics
- Detailed performance metrics
- Advanced behavioral analysis
- Sophisticated analytics
- In-depth performance tracking
- Driver performance metrics
- Driver analytics
- Total miles driven
- Driver efficiency
- Driver scores
- Performance indicators
- Driver statistics

**Key Keywords:** advanced analytics, detailed metrics, performance breakdown, sophisticated analytics, driver analytics, performance metrics, driver score, efficiency, total miles, driver statistics

---

## Driver_emergency

**Description:** Stores emergency contact information and emergency response procedures. Includes multiple emergency contacts (names, relationships, phone numbers), medical emergency information (allergies, medical conditions, medication requirements), emergency procedures/protocols, and critical information for emergency situations.

**Use for questions about:**
- Emergency contacts
- Emergency information
- Medical information
- Emergency procedures
- Medical conditions
- Emergency response

**Key Keywords:** emergency contact, emergency information, medical emergency, emergency procedures

---

## Driver_employment

**Description:** Contains employment details and work-related information. Includes hire date, position/job title, employment status (active, on leave, terminated), department assignments, manager information/reporting structure, work location, shift patterns, base salary, employment type (full-time, part-time, contractor), and employment-related data.

**Use for questions about:**
- Employment details
- Hire date
- Job title
- Employment status
- Department
- Manager information
- Shift patterns
- Employment type

**Key Keywords:** employment, hire date, job title, employment status, department, manager, shift

---

## Driver_financial

**Description:** Manages financial information and compensation details. Includes base salary, hourly rate, bonus eligibility/structures, benefits information, payment details (bank account for direct deposit), compensation structure, incentive program participation, and financial records.

**Use for questions about:**
- Driver salary
- Compensation
- Payment information
- Benefits
- Bonus information
- Financial details

**Key Keywords:** salary, compensation, payment, benefits, bonus, financial information

---

## Driver_license

**Description:** Contains comprehensive driver license information and credentials. Includes license number, license type/class (commercial, private), issuing state/country, issue date, expiry date, license status (valid, expired, suspended), license image storage references, and renewal information.

**Use for questions about:**
- Driver license
- License number
- License expiration
- License status
- License type
- License validity
- License renewal

**Key Keywords:** license, driver license, license number, license expiration, license status, license type

---

## Driver_medical

**Description:** Manages medical information and health-related compliance records. Includes health check results/dates, medical certificates (fitness for duty), fitness status indicators, medical clearance documentation, periodic health examination records, and medical restrictions/accommodations.

**Use for questions about:**
- Medical information
- Health checks
- Medical certificates
- Fitness status
- Medical clearance
- Health compliance

**Key Keywords:** medical, health check, medical certificate, fitness status, medical clearance, health compliance

---

## Driver_performance

**Description:** Contains performance evaluation data, reviews, and performance tracking. Includes safety scores, efficiency ratings, improvement areas, performance review records (dates, evaluator information), performance tracking data over time, and comprehensive performance metrics.

**Use for questions about:**
- Performance evaluation
- Performance reviews
- Performance metrics
- Safety scores
- Efficiency ratings
- Performance tracking

**Key Keywords:** performance, performance review, performance evaluation, performance metrics, performance tracking

---

## Driver_preferences

**Description:** Stores driver-specific operational preferences and work-related preferences. Includes shift preferences, assignment preferences (preferred vehicle types/routes), operational requirements/constraints, work schedule preferences, geographic preferences for assignments, and driver-specific operational settings.

**Use for questions about:**
- Driver preferences
- Shift preferences
- Assignment preferences
- Work schedule preferences
- Driver preferences and settings

**Key Keywords:** preferences, shift preferences, assignment preferences, work preferences

---

## Driver_Profile

**Description:** Contains complete comprehensive profile of a driver including all personal and professional information. Includes personal information (date of birth, gender, nationality), comprehensive professional details, complete profile data aggregating information from various sources, and all available information about the driver in a consolidated format.

**Use for questions about:**
- Complete driver profile
- Driver personal information
- Full driver details
- Driver profile information

**Key Keywords:** driver profile, profile information, complete profile, personal information

---

## Driver_status

**Description:** Tracks current real-time operational status. Includes availability status, assignment status, operational state (on-duty, off-duty, on-break), current location if tracked, real-time status information, and status flags/indicators affecting availability or operational capability.

**Use for questions about:**
- Current driver status
- Driver availability
- Driver operational state
- Real-time driver status
- On-duty/off-duty status

**Key Keywords:** driver status, availability, operational state, on-duty, off-duty, real-time status

---

## Driver_visa

**Description:** Manages visa and work permit information for international drivers or drivers working in foreign countries. Includes visa details (type, number, validity), work permit information (permit numbers, expiration dates), immigration status, visa expiration tracking, renewal information, and documentation related to legal work authorization.

**Use for questions about:**
- Visa information
- Work permit
- Immigration status
- Visa expiration
- Work authorization

**Key Keywords:** visa, work permit, immigration, visa expiration, work authorization

---

## Driver_wasl_logs

**Description:** Contains WASL (Saudi Arabia transport authority) integration logs and compliance records for drivers operating in Saudi Arabia. Includes WASL registration information, compliance logs, regulatory integration data, WASL system synchronization records, and data related to integration with Saudi Arabia's transport authority systems.

**Use for questions about:**
- WASL integration
- Saudi Arabia compliance
- WASL logs
- WASL registration
- Saudi transport authority

**Key Keywords:** WASL, Saudi Arabia, transport authority, WASL logs, WASL registration, compliance

---

## Events_base

**Description:** Contains logs/notifications for SystemAlertRule triggers only. This collection stores the actual event logs when SystemAlertRule rules are triggered/fired. Only these specific event types are stored: Idling, Driving Without GPS Lock, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, driving with low battery. Each event record includes event type classification, precise location coordinates (latitude, longitude), timestamp, event severity level, basic event details, and device context information. Note: This collection contains ONLY SystemAlertRule logs. It does NOT contain AlertRule logs (those are in AlertHistory_base). It does NOT contain geofence events (those are in AlertHistory_base). SystemAlertRule rules/definitions are in SystemAlertRule_base.

**Use for questions about:**
- SystemAlertRule notifications/logs (when system rules are triggered)
- Event logs for: Idling, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, driving with low battery
- When system alerts were triggered
- System Alert trigger logs

**Key Keywords:** events, notifications, logs, system alert notifications, event logs, trigger logs, SystemAlertRule logs, Idling, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, driving with low battery

---

## Geofence_base

**Description:** Contains core definitions and configurations for geographical boundaries and virtual perimeters (geofence rules/definitions). Includes geofence name, geofence type (circular with radius, polygonal with coordinate arrays), precise coordinates defining the geographical area, radius measurements for circular geofences, operational status (active/inactive), and configuration settings. Note: This collection contains only geofence rules and definitions. Geofence events/notifications (when geofences are entered/exited) are stored in AlertHistory_base.

**Use for questions about:**
- Geofence definitions
- Geofence boundaries
- Geofence zones
- Geofence configuration
- Geofence locations
- Geofence status

**Key Keywords:** geofence, geographical boundary, zone, geofence definition, geofence location, virtual perimeter

---

## Geofence_asset_assignment

**Description:** Manages relationships between geofences and specific assets monitored within those zones. Includes assigned asset IDs, assignment status, monitoring configurations, and asset-specific geofence settings.

**Use for questions about:**
- Which assets are monitored in geofences
- Geofence-asset assignments
- Assets in geofence zones
- Geofence monitoring for assets

**Key Keywords:** geofence assignment, assets in geofence, geofence monitoring, asset-geofence relationship

---

## SystemAlertRule_base

**Description:** Contains predefined system-level alert rules and configurations for global fleet monitoring (rules/definitions only). Includes global alert settings applying across the entire system, default notification preferences, system-wide alert policies, event-based rules for common fleet scenarios (idling detection, maintenance reminders), and system health monitoring rules. Note: This collection contains only SystemAlertRule rules and definitions. The logs/notifications for when SystemAlertRule triggers are fired are stored in Events_base collection, not here.

**Use for questions about:**
- System alert rules (definitions)
- Global alert settings
- Default alert rules
- System-wide alert policies
- System monitoring rules (configuration)

**Key Keywords:** system alert rule, global alert, system-wide alert, default alert, system monitoring, system alert rule definition

---

## Trip_base

**Description:** Contains comprehensive tracking and management information for all vehicle trips and journeys. Each trip record includes unique trip_id, precise start location coordinates/timestamp, end location coordinates/timestamp, trip duration, total distance covered, driver identification, vehicle identification (asset_id), start/end odometer readings, start/end fuel levels, distance calculations (actual and orthodromic), average/maximum speed, duration of idling, and comprehensive trip metadata.

**Use for questions about:**
- Trip information
- Trip history
- Trip duration
- Trip distance
- Trip start/end locations
- Trip details
- Journey information
- Route information

**Key Keywords:** trip, journey, trip history, trip duration, trip distance, route, trip details

---

## Trip_Analytics

**Description:** Extends trip data with comprehensive performance analytics and behavioral metrics for each completed journey. Includes driving behavior scores (safety, efficiency), fuel efficiency calculations, safety metrics (harsh braking, acceleration, cornering incidents during trip), driving patterns, route analysis, trip performance indicators, and detailed analytics.

**Use for questions about:**
- Trip performance analytics
- Trip behavior scores
- Trip fuel efficiency
- Trip safety metrics
- Trip analytics
- Trip performance indicators

**Key Keywords:** trip analytics, trip performance, trip behavior, trip efficiency, trip safety, trip metrics

---

## Collection Selection Guide

### Location & Tracking Questions
Use: `AvlRecord_base`, `AvlRecord_sensor`, `Trip_base`, `Geofence_base`, `Geofence_asset_assignment`

### Driver Questions
Use: `Driver_base` + `Driver_Profile` + relevant Driver subcollections (e.g., `Driver_license` for license questions, `Driver_analytics` for performance). Note: When any Driver subcollection is selected, `Driver_base` and `Driver_Profile` are automatically included.

### Vehicle/Asset Questions
Use: `asset_base` + relevant asset_details subcollections (e.g., `asset_details_base` for specifications, `asset_details_cost_finance` for financial)

### Alert Questions
- For AlertRule trigger logs/notifications: `AlertHistory_base`
- For SystemAlertRule trigger logs/notifications: `Events_base`
- For AlertRule rule definitions: `AlertRule_base` + AlertRule subcollections
- For SystemAlertRule rule definitions: `SystemAlertRule_base`

### Geofence Questions
- For geofence rules/definitions: `Geofence_base` + `Geofence_asset_assignment`
- For geofence events/notifications that were triggered: `AlertHistory_base`

### System Alert Rule Questions
- For SystemAlertRule rule definitions: `SystemAlertRule_base`
- For SystemAlertRule trigger logs/notifications: `Events_base`

### Events & Incidents (Driving Behavior Events)
- For SystemAlertRule trigger logs: `Events_base` (Idling, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, driving with low battery)
- For AlertRule trigger logs: `AlertHistory_base`
- For geofence events: `AlertHistory_base`

### Performance & Analytics Questions
Use: `DailyAnalytics_base`, `Driver_analytics`, `Trip_Analytics`, `Driver_behavior`

### Maintenance & Compliance
Use: `asset_details_maintenance_logs`, `asset_details_document_status_flags`, `Driver_compliance`, `Driver_medical`

### Financial & Cost Questions
Use: `asset_details_cost_finance`, `Driver_financial`

---

**Note:** Each subcollection is treated as an independent collection for RAG retrieval purposes. When a user asks a question, match the question intent and keywords to the appropriate collection(s) above to retrieve the most relevant chunks.

---

## Important Collection Distinctions

### Rules vs Logs/Notifications

**Rules/Definitions Collections** (contain only rule configurations):
- `AlertRule_base` + subcollections: AlertRule rule definitions
- `SystemAlertRule_base`: SystemAlertRule rule definitions
- `Geofence_base` + `Geofence_asset_assignment`: Geofence rule definitions

**Logs/Notifications Collections** (contain actual trigger events):
- `Events_base`: Contains logs/notifications for SystemAlertRule triggers ONLY (Idling, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, driving with low battery). Does NOT contain AlertRule logs or geofence events.
- `AlertHistory_base`: Contains logs/notifications for AlertRule triggers and ALL geofence events/notifications (entry, exit, violations). Does NOT contain SystemAlertRule logs.

### Summary Table

| Collection Type | Rules/Definitions | Logs/Notifications |
|----------------|-------------------|-------------------|
| AlertRule | `AlertRule_base` + subcollections | `AlertHistory_base` |
| SystemAlertRule | `SystemAlertRule_base` | `Events_base` |
| Geofence | `Geofence_base` + `Geofence_asset_assignment` | `AlertHistory_base` |

### Driver Collection Auto-Selection

When any Driver subcollection is selected (e.g., `Driver_visa`, `Driver_license`), the system automatically includes:
- `Driver_base`
- `Driver_Profile`

This ensures complete driver information is always available.

