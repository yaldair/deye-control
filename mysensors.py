from sunsynk import WATT
from sunsynk.sensors import Sensor, SensorDefinitions

SENSORS = SensorDefinitions()

# Interne meting op de grid-klemmen van de Deye ("LD" op het display)
SENSORS += (
    Sensor(604, "LD grid L1 power", WATT, -1),
    Sensor(605, "LD grid L2 power", WATT, -1),
    Sensor(606, "LD grid L3 power", WATT, -1),
    Sensor(607, "LD grid power", WATT, -1),
)

# LOAD-poort (backup/UPS-uitgang) = huis
SENSORS += (
    Sensor(640, "UPS load L1 power", WATT, -1),
    Sensor(641, "UPS load L2 power", WATT, -1),
    Sensor(642, "UPS load L3 power", WATT, -1),
    Sensor(643, "UPS load power", WATT, -1),
)

from sunsynk.rwsensors import NumberRWSensor, SelectRWSensor
SENSORS += (
    SelectRWSensor(1100, "RC mode", options={0: "Uit", 1: "Aan"}),
    NumberRWSensor(1101, "RC watchdog", "s", min=10, max=600),
    SelectRWSensor(1104, "RC side", options={0: "AC", 1: "Accu", 2: "Net"}),
    SelectRWSensor(1105, "RC battery mode", options={2: "Vermogen", 3: "SOC", 5: "Vermogen+SOC"}),
    SelectRWSensor(1106, "RC phase mode", options={0: "3 fasen samen", 1: "Per fase"}),
    NumberRWSensor(1109, "RC battery power", "%", -0.1, min=-45, max=45),   # + = ontladen, - = laden; 1 % = 120 W
    NumberRWSensor(1110, "RC soc", "%", 0.1, min=10, max=100),
    NumberRWSensor(1111, "RC total power", "%", -0.1, min=-20, max=20),     # net: + = afname, - = teruglevering
    NumberRWSensor(1115, "RC max solar", "%", 0.1, min=0, max=99.9),        # >= 100 % geeft 0 W
)
