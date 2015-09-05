# brewarm
Efficient temperature logging and displaying using w1 sensors, also supports cheap i2c 4digit led display on RPi with planned PID temperature control.  
This project was inspired by BrewPi because it had problems rendering logs with many datapoints and lacked hardware simplicity, so I created something simpler to use with your raspberry or any other platform supporting w1 sensors on linux with requirements to hardware as little as possible - you need just to hook up your sensors, that's it!  
"arm" in the name denotes that I am running it not only on RPi but also on other ARM platforms.

## features
* reading temperature from linux sysfs filesystem
* graphing multiple sensors on web ui using built in web server
* commenting on data points
* live graph updating using little network traffic to monitor temperature changes
* logging to ram and synchronizing to permanent storage only at defined intervals or shutdown to lessen storage wearing
* sensor data displaying on cheap 4digit lcd with TM1637 driver IC - supported only on R-PI because of RPi.GPIO library dependency
* system shutdown using gpio pin
* system time control
  * setting system clock from ui
  * force loading rtc clock on startup if exists
  * if system time is in future it is set to last log entry time
