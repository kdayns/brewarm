# brewarm
Efficient temperature logging using w1 sensors with PID temperature control, also supports cheap i2c 4digit led display on RPi.
Inspired by BrewPi but because of it's hardware complexity and slow log rendering with many datapoints I created something simpler to use with your raspberry or any other platform supporting w1 sensors on Linux with requirements to hardware as little as possible - you need just to hook up your sensors, that's it!
"arm" in the name denotes that I am running it not only on RPi but also on other ARM platforms.

## features
* uses csv format
* reading temperature from linux sysfs using kernel driver
* software fallback using w1 device rw file in sysfs
* oversampling to increase accuracy
* graphing multiple sensors on web ui using built in web server
* logging can be paused but only for last session
* commenting on data points
* switch PID control from one master sensor
* manual switch state control
* live graph updating using little network traffic
* logging is done to /tmp and synchronizing to permanent storage is done only at defined intervals or shutdown to lessen storage wearing
* system shutdown using gpio pin
* system time control
  * setting system clock from ui
  * force loading rtc clock on startup if exists
  * if system time is in future it is set to last log entry time to prevent log screwing
* R-PI only - sensor data displaying on cheap 4digit lcd with TM1637 driver IC (RPi.GPIO library dependency)

## WIP prioritized
* switch override
* pid reset
* sensor offset setting
* fermentation profile
* multiple switch state graphing
* w1 type detect in sw mode

## more info
* switch state may appear incorrect when rolling average is used, which is 10 by default
* timestamp is logged in local time, make sure your timezone is set
* sensors in log files are bound to ther name in configuration, changing sensor's name will prevent from correctly resuming session
* shutdown from ui will stop logging session and it will not auto resume on next startup
* saving configuration or adding comment also triggers reading sensors and storing data points
* to start new logging session configure sensors and then click on "+" then ok
* sensor configuration columns:
    * lcd radio button - reading from this sensor will be displayed if lcd is present
    * enabled check box - if logging for this sensor is active and if it should be added to new brew (addition later is not possible)
    * id - w1 id
    * state - current reading (updated at set update interval)
    * min - clipping temp
    * max - clipping temp
    * name - friendly name of sensor which also binds it's id to log file entry
    * remove button - delete sensor, present sensor will be readded by automatic discovery
* switch configuration columns:
    * UNUSED - planned for PID override
    * enabled check box - same as for temp sensor
    * id
    * state - current state also works as instant action button (red - off, green - on)
    * PID set point
    * PID control direction
    * name
    * remove button
