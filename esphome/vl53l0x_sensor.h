/* This example shows how to use continuous mode to take
range measurements with the VL53L0X. It is based on
vl53l0x_ContinuousRanging_Example.c from the VL53L0X API.

The range readings are in units of mm. */

#include <Wire.h>
#include <VL53L0X.h>

// Include esphome
#include "esphome.h"

// Uncomment this line to use long range mode. This
// increases the sensitivity of the sensor and extends its
// potential range, but increases the likelihood of getting
// an inaccurate reading because of reflections from objects
// other than the intended target. It works best in dark
// conditions.

#define LONG_RANGE

class VL53L0XSensor : public PollingComponent, public Sensor {
  public:
  VL53L0X sensor;

  VL53L0XSensor(int update_interval) : PollingComponent(update_interval){}
  
  void setup() override {
    Wire.begin();
  
    sensor.init();
    sensor.setTimeout(1000);
  
    #if defined LONG_RANGE
    // lower the return signal rate limit (default is 0.25 MCPS)
    sensor.setSignalRateLimit(0.1);
    // increase laser pulse periods (defaults are 14 and 10 PCLKs)
    sensor.setVcselPulsePeriod(VL53L0X::VcselPeriodPreRange, 18);
    sensor.setVcselPulsePeriod(VL53L0X::VcselPeriodFinalRange, 14);
    #endif
    
    // Start continuous back-to-back mode (take readings as
    // fast as possible).  To use continuous timed mode
    // instead, provide a desired inter-measurement period in
    // ms (e.g. sensor.startContinuous(100)).
    //sensor.startContinuous();
  }

  void update() override {
    int reading1 = sensor.readRangeSingleMillimeters();
    // int reading2 = sensor.readRangeContinuousMillimeters();
    // int reading3 = sensor.readRangeContinuousMillimeters();
    // int averageReading = ((reading1+reading2+reading3)/3);
    publish_state(reading1);
    ESP_LOGD("vl53l0x", "Salt level is: %f mm", this->state);
    if (sensor.timeoutOccurred()) { ESP_LOGD("vl53l0x", " TIMEOUT"); }
  }
};
