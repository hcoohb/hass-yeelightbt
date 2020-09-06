# Home Assistant custom component for Yeelight Bedside lamp

This is a custom component for Home Assistant that allows the control of the Yeelight bedside Lamp via bluetooth. (Contrary to the wifi version, those lamps only have bluetooth control).

Originally based on the work by Teemu Rytilahti [python-yeelightbt](https://github.com/rytilahti/python-yeelightbt), it has been completely re-written to improve stability and only focuses on the integration with HA.


# Installation


## Manual Installation

1. Download the `hass-yeelight_bt.zip` file from the
   [latest release](https://github.com/hcoohb/hass-yeelightbt/releases/latest).
2. Unpack the release and copy the `custom_components/yeelight_bt` directory
   into the `custom_components` directory of your Home Assistant
   installation.
3. install bluepy in the HA virtual environment
4. Add the `yeelight_bt` lights as described in next section.


## Using HACS

While not being part yet of the default repos, just add this github as a repo in hacs and you will be able to install the component from HACS.

## Give bluetooth permissions !

This component use the `bluepy` python library to access bluetooth.
In case you are getting "No such file or directory" error for bluepy-helper, you have to go into bluepy's directory and run make there.

If it is not already done, the blupy-helper program will need permissions to acces bluetooth as a regular user. It can be done by doing the following:

```
sudo setcap cap_net_admin,cap_net_raw+eip /PATH-TO-HA-VENV/PATH-TO-BLUEPY-LIB/bluepy-helper
```


# Homeassistant component configuration

## Using the integrations menu

In Configuration/Integrations click on the + button, select `Yeelight bluetooth` and configure the name and mac address on the form.
The light is automatically added and a device is created.


## Using configuration.yaml

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

# TODO

- [x] Re-implement bluetooth backend for stability and optimal responsivness for yeelight
- [x] Add component to HACS for easy install
- [x] Allow configuration through the integration UI
- [ ] Enable discovery of lamps in UI? (Not sure if possible)
- [ ] Look into setting up effect and flow (low priority)
- [ ] Allow pairing process with new device
- [ ] Support for candela light? (I do not have a device, so might need help from someone with one...)
