/*
 * Scenario prompts. These are ILLUSTRATIVE inputs written for demonstration — not measurements from
 * real equipment. They only pre-fill the question box; the diagnosis always comes from the backend
 * harness. Values sit near the patterns present in the knowledge base so retrieval has something to
 * compare against, and every fault named in a title is one of the existing AFRB labels.
 */
export const SAMPLES = {
  afrb: [
    { group: 'fault', tag: 'Clear fault', q: 'Slurry pump in a mineral processing facility: temperature 95.0 °C, vibration 0.790, pressure 55.0 PSI, 2400 RPM, current 55.0 A, voltage 310.0 V, flow rate 100.0 L/min. What is the most likely fault?' },
    { group: 'fault', tag: 'Pump problem', q: 'Centrifugal pump: temperature 60 °C, vibration 0.55, pressure 22 PSI, 2400 RPM, current 70 A, voltage 325 V, flow rate 48 L/min. What failure does this indicate?' },
    { group: 'fault', tag: 'Bearing overheating', q: 'Electric motor driving a conveyor belt: temperature 88.0 °C at the drive-end housing, vibration 0.700, pressure 54.0 PSI, 2450 RPM, current 61.0 A, voltage 312.0 V, flow rate 100.0 L/min. Temperature and vibration have both climbed over the last shift. What is the most likely fault?' },
    { group: 'fault', tag: 'Motor overload', q: 'Axial fan motor in a steel mill ventilation system: temperature 80.0 °C, vibration 0.210, pressure 53.0 PSI, 2300 RPM, current 97.0 A, voltage 386.0 V, flow rate 105.0 L/min. Current draw is well above its usual level. What is causing this?' },
    { group: 'fault', tag: 'Pump cavitation', q: 'Centrifugal pump in a municipal water treatment plant: temperature 57.0 °C, vibration 0.450, pressure 29.0 PSI and fluctuating, 2500 RPM, current 67.0 A, voltage 330.0 V, flow rate 62.0 L/min and unstable. What is the most likely fault?' },
    { group: 'fault', tag: 'Lubrication failure', q: 'Process gas compressor: temperature 92.0 °C, vibration 0.550, pressure 54.0 PSI, 2500 RPM, current 77.0 A, voltage 316.0 V, flow rate 97.0 L/min. Temperature and current keep rising between oil changes, suggesting increasing friction. Diagnose.' },
    { group: 'fault', tag: 'Normal equipment', q: 'Booster pump station: temperature 54.0 °C, vibration 0.140, pressure 52.0 PSI, 2000 RPM, current 60.0 A, voltage 330.0 V, flow rate 110.0 L/min. Is anything wrong?' },
    { group: 'data', tag: 'Missing sensor', q: 'Gearbox driving a paper mill roller: temperature reading unavailable, vibration 0.810, pressure 50.0 PSI, 2200 RPM, current 75.0 A, voltage 330.0 V, flow rate 100.0 L/min. Diagnose.' },
    { group: 'data', tag: 'Conflicting signals', q: 'Cooling tower circulation pump: temperature 56.0 °C, vibration 0.880, pressure 51.0 PSI, 2100 RPM, current 61.0 A, voltage 330.0 V, flow rate 108.0 L/min. What is wrong?' },
    { group: 'data', tag: 'Sensor drift', q: 'High-pressure feed pump in a petrochemical refinery: temperature 16.0 °C, vibration 0.200, pressure 55.0 PSI, 4000 RPM, current 143.0 A, voltage 326.0 V, flow rate 121.0 L/min. The temperature looks implausibly low for this load. Can these readings be trusted, and what is the likely fault?' },
    { group: 'data', tag: 'No historical match', q: 'Axial fan unit: temperature 118.0 °C, vibration 0.040, pressure 97.0 PSI, 4800 RPM, current 30.0 A, voltage 470.0 V, flow rate 190.0 L/min. What is wrong?' },
    { group: 'data', tag: 'Qualitative only', q: 'Predict failure from elevated vibration and temperature readings.' },
  ],
  // Real measured knowledge base (UCI #447 hydraulic test rig). Prompts use values typical of each recorded
  // condition but are still illustrative inputs; the rig has no RPM, current or voltage sensors.
  hydraulic: [
    { group: 'fault', tag: 'Hot oil, low flow', q: 'Hydraulic power unit: temperature 54.2 °C, vibration 0.65, pressure 158 bar, flow rate 6.48 L/min. What is the most likely fault?' },
    { group: 'fault', tag: 'Accumulator pressure', q: 'Hydraulic power unit: temperature 36.3 °C, vibration 0.565, pressure 160.5 bar, flow rate 6.65 L/min. Pressure recovery after each load step feels sluggish. What is the most likely fault?' },
    { group: 'fault', tag: 'Pump leakage', q: 'Hydraulic power unit: temperature 36.3 °C, vibration 0.543, pressure 160.4 bar, flow rate 6.42 L/min. Delivered flow is slightly down at constant load. Diagnose.' },
    { group: 'fault', tag: 'Valve switching', q: 'Hydraulic power unit: temperature 36.25 °C, vibration 0.55, pressure 160.6 bar, flow rate 6.49 L/min. Cycle timing has drifted. What is the most likely fault?' },
    { group: 'fault', tag: 'Healthy cycle', q: 'Hydraulic power unit: temperature 36.0 °C, vibration 0.551, pressure 161.0 bar, flow rate 6.71 L/min. Is anything wrong?' },
    { group: 'data', tag: 'Missing temperature', q: 'Hydraulic power unit: temperature reading unavailable, vibration 0.6, pressure 158 bar, flow rate 6.5 L/min. Diagnose.' },
  ],
  failure_iq: [
    { tag: 'Sensor → events', q: 'Which failure is likely when winding temperature rises in an electric motor?' },
    { tag: 'Sensor → events', q: 'What does abnormal oil debris indicate in a compressor?' },
    { tag: 'Sparse data', q: 'Why is vibration increasing in the pump?' },
  ],
}
export const SAMPLE_GROUPS = [
  { id: 'fault', title: 'Fault patterns' },
  { id: 'data', title: 'Data quality & edge cases' },
]

