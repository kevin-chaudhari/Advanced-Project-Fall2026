from harness.query_prep import prepare_query


def test_extracts_all_sensor_values():
    p = prepare_query("Fan unit: temperature 105.1 °C, vibration 0.166, pressure 46.1 PSI, 1604 RPM, "
                      "current 16.0 A, voltage 370.1 V, flow rate 8.1 L/min.")
    assert p.sensors == {"temperature": 105.1, "vibration": 0.166, "pressure": 46.1, "rpm": 1604.0,
                         "current": 16.0, "voltage": 370.1, "flow_rate": 8.1}
    assert p.equipment_type == "fan"


def test_missing_channel_is_not_invented():
    p = prepare_query("Pump: temperature reading unavailable, vibration 0.81, current 60 A")
    assert "temperature" not in p.sensors
    assert "temperature" in p.missing_sensors


def test_unit_conversion_and_incompatible_units():
    p = prepare_query("pump pressure dropped to 2.1 bar and vibration 7.4 mm/s")
    assert abs(p.sensors["pressure"] - 30.5) < 0.1
    assert "vibration" not in p.sensors            # mm/s is not the KB's normalised index
    assert any("mm/s" in n for n in p.notes)


def test_qualitative_directions():
    p = prepare_query("Predict failure from elevated vibration and temperature readings.")
    assert p.qualitative == {"vibration": "high", "temperature": "high"}
    assert p.sensors == {}
