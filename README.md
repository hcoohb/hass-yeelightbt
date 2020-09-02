# Home Assistant custom component for Yeelight Bedside lamp

This is a custom component for Home Assistant that allows the control of the Yeelight bedside Lamp via bluetooth. (Contrary to the wifi version, those lamps only have bluetooth control).

Originally based on the work by Teemu Rytilahti [python-yeelightbt](https://github.com/rytilahti/python-yeelightbt), it has been heavily modified to improve stability and only focuses on the integration with HA.

# Installation


### MANUAL INSTALLATION

1. Download the `hass-yeelight_bt.zip` file from the
   [latest release](https://github.com/hcoohb/hass-yeelightbt/releases/latest).
2. Unpack the release and copy the `custom_components/yeelight_bt` directory
   into the `custom_components` directory of your Home Assistant
   installation.
3. Add the `yeelight_bt` lights as described in next section.

This component use the `bluepy` python library to access bluetooth.
In case you are getting "No such file or directory" error for bluepy-helper, you have to go into bluepy's directory and run make there.
It is also a good idea to let the helper to have capabilities for accessing the bluetooth devices without being root, e.g., by doing the following:

```
setcap cap_net_admin,cap_net_raw+eip bluepy-helper
```


# Homeassistant configuration

### USING configuration.yaml

1. For each lamp, create a light with the `yeelight_bt` platform and configure the `name` and `mac` address.
    
    Example:
    ```yaml
    light:
      - platform: yeelight_bt
        name: Bedside lamp
        mac: 'f8:24:41:xx:xx:xx'
      - platform: yeelight_bt
        name: Other lamp
        mac: 'f8:24:41:xx:xx:xx'
    ```

2. Restart Home Assistant.

### USING the integrations menu

In Configuration/Integrations click on the + button, select `Yeelight bluetooth` and configure the name and mac address on the form.
The light is automatically added and a device is created.


