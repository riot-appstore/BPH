#! /usr/bin/env python3
# Copyright (c) 2019 Kevin Weiss, for HAW Hamburg  <kevin.weiss@haw-hamburg.de>
#
# This file is subject to the terms and conditions of the MIT License. See the
# file LICENSE in the top level directory for more details.
# SPDX-License-Identifier:    MIT

"""
This script handles interfacing to the BPH.  It handles the gpio, power
management/measurement.

The purpose of this script is allow easy setup and manual usage of the BPH.

Usage
-----

```
usage: bph_shell.py     [-h]
                        [--loglevel {debug,info,warning,error,fatal,critical}]
                        [--init_state]
                        [--pin_config_path]
                        [--pin_config_filename]

optional arguments:
  -h, --help            show this help message and exit
  --loglevel, -l {debug,info,warning,error,fatal,critical}
                        Python logger log level (default: warning)
  --init_state, -is
                        Initialized pins to default state on start
  --pin_config_path, -pp
                        Path to the board configuration file
  --pin_config_filename, -pf
                        Filename of the board config file
```
"""

import logging
import argparse
import time
import os
import glob
from pathlib import Path
from json import load, decoder
from pprint import pprint
import subprocess
from cmd import Cmd
try:
    from .driver_ina226 import INA226
except (ImportError, SystemError):
    try:
        from bph_pal.driver_ina226 import INA226
    except (ImportError, SystemError):
        from driver_ina226 import INA226
try:
    import readline
except ImportError:
    print("Cannot import readline, cannot use history")
    readline = None
try:
    import wiringpi
except ImportError:
    print("Cannot import wiring pi, resorting to printing")
    wiringpi = None


class BphShell(Cmd):

    prompt = "BPH: "

    def __init__(self, path=None, filename='bph_pinout_v2c.json',
                 init_state=False):
        if path is None:
            path = str(Path(__file__).parents[0]) + '/config/'
        full_path = os.path.join(path, filename)
        with open(full_path) as bph_pinout_file:
            bph_pinout = load(bph_pinout_file)
        self.gpio_map = bph_pinout['gpio']
        self.shunt = bph_pinout['shunt_res']
        self._set_gpio_map(self.gpio_map, init_state)
        self.curmon = INA226(0x44, shunt_val=self.shunt['high_range']['val'])
        Cmd.__init__(self)

    def preloop(self):
        if readline:
            try:
                readline.read_history_file()
            except IOError:
                pass

    def do_load_pinmap(self, arg):
        """Loads and sets pinout states of BPH according to config file

        Usage:
            load_pinmap <path_to_config_file>

        Args:
            path_to_config_file: Path and filename of the config
                                 FileExistsError
        """
        try:
            with open(arg) as bph_pinout_file:
                bph_pinout = load(bph_pinout_file)
            self.gpio_map = bph_pinout['gpio']
            self._set_gpio_map(self.gpio_map, True)
        except (FileNotFoundError, decoder.JSONDecodeError) as exc:
            print(exc)

    @staticmethod
    def complete_load_pinmap(text, line, begidx, endidx):
        """Completes arg for path and filename"""
        text = text
        before_arg = line.rfind(" ", 0, begidx)
        if before_arg == -1:
            # arg not found
            return
        # fixed portion of the arg
        fixed = line[before_arg+1:begidx]
        arg = line[before_arg+1:endidx]
        pattern = arg + '*'

        completions = []
        for path in glob.glob(pattern):
            if path and os.path.isdir(path) and path[-1] != os.sep:
                path = path + os.sep
            completions.append(path.replace(fixed, "", 1))
        return completions

    def do_set_pin(self, arg):
        """Turns the pin high
        Usage:
            set_pin <pin_name>

        Args:
            pin_name: Pin name or key
        """
        try:
            self._write_pin_state(arg, 1)
        except (ValueError, TypeError, KeyError) as exc:
            print(exc)

    def complete_set_pin(self, text, line, begidx, endidx):
        """Completes arg with possible pin names"""
        begidx = begidx
        endidx = endidx
        return self._show_pins(text, line)

    def do_clear_pin(self, arg):
        """Turns the pin low
        Usage:
            clear_pin <pin_name>

        Args:
            pin_name: Pin name or key
        """
        try:
            self._write_pin_state(arg, 0)
        except (ValueError, TypeError, KeyError) as exc:
            print(exc)

    def complete_clear_pin(self, text, line, begidx, endidx):
        """Completes arg with possible pin names"""
        begidx = begidx
        endidx = endidx
        return self._show_pins(text, line)

    def do_input_pin(self, arg):
        """Turns the input for high impedance
        Usage:
            input_pin <pin_name>

        Args:
            pin_name: Pin name or key
        """
        try:
            self._pin_to_input(arg)
        except (ValueError, TypeError, KeyError) as exc:
            print(exc)

    def complete_input_pin(self, text, line, begidx, endidx):
        """Completes arg with possible pin names"""
        begidx = begidx
        endidx = endidx
        return self._show_pins(text, line)

    def do_philip_reset(self, arg):
        """Provides a hard reset on PHiLIP board
        Usage:
            philip_reset
        """
        arg = arg
        self.do_clear_pin("BP_RST")
        time.sleep(0.3)
        self.do_input_pin("BP_RST")
        time.sleep(0.2)

    def do_power_source(self, arg):
        """Selects the power settings
        Usage:
            power_source <selection>

        Args:
            selection: The type of power mode to set
                       [external, none, all, usb]
        """
        if arg == "external":
            print("external power on, USB power off, PHiLIP on")
            self._set_usb(False)
            self._pin_to_input("BP_RST")
            self._write_pin_state("EXT_V_EN", 1)
        elif arg == "none":
            print("external power off, USB power off, PHiLIP off")
            self._set_usb(False)
            self._write_pin_state("BP_RST", 0)
            self._write_pin_state("EXT_V_EN", 0)
        elif arg == "all":
            print("external power on, USB power on, PHiLIP on")
            self._set_usb(True)
            self._pin_to_input("BP_RST")
            self._write_pin_state("EXT_V_EN", 1)
        elif arg == "usb":
            print("external power off, USB power on, PHiLIP on")
            self._set_usb(True)
            self._pin_to_input("BP_RST")
            self._write_pin_state("EXT_V_EN", 0)
        else:
            print("Invalid argument, no power change")

    @staticmethod
    def _set_usb(usb_on):
        subprocess.run("echo '1-1' | sudo tee /sys/bus/usb/drivers/usb/{} "
                       "> /dev/null".format("bind" if usb_on else "unbind"),
                       shell=True)

    @staticmethod
    def complete_power_source(text, line, begidx, endidx):
        """Completes arg with possible power source settings"""
        begidx = begidx
        endidx = endidx
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        power_opts = ['external', 'none', 'all', 'usb']
        return [s[offs:] for s in power_opts if s.startswith(mline)]

    def do_read_current(self, arg):
        """Reads current to the dut thorugh the ext voltage line
        Usage:
            read_current [range]

        Args:
            range: The range settings
                   [high_range<200mA, low_range<50uA]
        """
        func_args = (arg or '').split()
        try:
            if len(func_args) is 0:
                print("Current = {} A".format(self.curmon.get_current()))
            elif len(func_args) is 1:
                if func_args[0] == "high_range":
                    self._write_pin_state("RES_BYP", 1)
                    self.curmon.set_shunt(self.shunt['high_range']['val'])
                elif func_args[0] == "low_range":
                    self._write_pin_state("RES_BYP", 0)
                    self.curmon.set_shunt(self.shunt['low_range']['val'])
                else:
                    raise KeyError
                time.sleep(0.3)
                print("Current = {}A".format(self.curmon.get_current()))
        except KeyError as exc:
            print('Could not parse argument {}'.format(exc))
        except (TypeError, ValueError, SyntaxError) as exc:
            print(exc)

    @staticmethod
    def complete_read_current(text, line, begidx, endidx):
        """Completes arg with possible ranges"""
        begidx = begidx
        endidx = endidx
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        power_opts = ['high_range', 'low_range']
        return [s[offs:] for s in power_opts if s.startswith(mline)]

    def do_read_voltage(self, arg):
        """Reads voltage to the dut thorugh the ext voltage line
        Usage:
            read_current [voltage_type=bus]

        Args:
            voltage_type: The voltage types...
                          [bus, shunt]
        """
        func_args = (arg or '').split()
        try:
            if len(func_args) is 0:
                print("Bus = {} V".format(self.curmon.get_bus_voltage()))
            elif len(func_args) is 1:
                if func_args[0] == "bus":
                    print("Bus = {} V".format(self.curmon.get_bus_voltage()))
                elif func_args[0] == "shunt":
                    print("Shunt = {} V"
                          "".format(self.curmon.get_shunt_voltage()))
                else:
                    raise KeyError
        except KeyError as exc:
            print('Could not parse argument {}'.format(exc))
        except (TypeError, ValueError, SyntaxError) as exc:
            print(exc)

    @staticmethod
    def complete_read_voltage(text, line, begidx, endidx):
        """Completes arg with possible voltage types"""
        begidx = begidx
        endidx = endidx
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        power_opts = ['bus', 'shunt']
        return [s[offs:] for s in power_opts if s.startswith(mline)]

    @staticmethod
    def do_show_pinout(arg):
        """Prints the pinout for the connected board

        Usage:
            show_pinout
        """
        arg = arg
        print("""
[20]     - brown  - DEBUG0_OUT
    [19] - red    - DUT_ADC
[18]     - orange - DEBUG1_OUT
    [17] - yellow - DUT_TX
[16]     - green  - DEBUG2_OUT
    [15] - blue   - DUT_RX
[14]     - purple - EXT_V_OUT
    [13] - grey   - DUT_RTS
[12]     - white  - DAC_OUT
    [11] - black  - DUT_CTS
[10]     - brown  - DUT_PWM
    [ 9] - red    - DUT_RST
[ 8]     - orange - DUT_SDA
    [ 7] - yellow - GND
[ 6]     - green  - DUT_SCL
    [ 5] - blue   - DUT_IC
[ 4]     - purple - DUT_MOSI
    [ 3] - grey   - DUT_MISO
[ 2]     - white  - DUT_SCK
    [ 1] - black  - DUT_NSS
""")

    def do_pinmap(self, arg):
        """Shows the pinmap states and description
        Usage:
            pinmap
        """
        arg = arg
        pprint(sorted(self.gpio_map.items()))

    @staticmethod
    def _set_gpio_map(gpio_map, initialize):
        logging.debug('Setting defaults')
        if wiringpi is None:
            logging.info("Setting up gpio")
        else:
            wiringpi.wiringPiSetupGpio()
        for gpio_value in gpio_map.values():
            logging.debug("Setting GPIO %r: on pin %r to %r",
                          gpio_value['name'],
                          gpio_value['pin'],
                          gpio_value['mode'])
            if initialize:
                if wiringpi is None:
                    logging.info("Pin %r mode is %r", gpio_value['pin'],
                                 gpio_value['mode'])
                else:
                    wiringpi.pinMode(gpio_value['pin'], gpio_value['mode'])
            if 'state' in gpio_value and initialize:
                if wiringpi is None:
                    logging.info("Pin %r state is %r", gpio_value['pin'],
                                 gpio_value['state'])
                else:
                    wiringpi.digitalWrite(gpio_value['pin'],
                                          gpio_value['state'])
                logging.debug("State is %r", gpio_value['state'])

    def _pin_to_input(self, arg):
        pin_num, pin_key = self._get_pin_num_and_key(arg)
        if wiringpi is None:
            logging.info("Pin %r mode is %r", pin_num, 0)
            self.gpio_map[pin_key]['mode'] = 0
        else:
            wiringpi.pinMode(pin_num, wiringpi.GPIO.INPUT)
            self.gpio_map[pin_key]['mode'] = wiringpi.GPIO.INPUT
        self.gpio_map[pin_key].pop("state", None)

    def _show_pins(self, text, line):
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in self.gpio_map.keys() if s.startswith(mline)]

    def _write_pin_state(self, arg, state):
        pin_num, pin_key = self._get_pin_num_and_key(arg)
        logging.debug("Writing pin %r for %r to %r", pin_num, pin_key, state)
        if wiringpi is None:
            logging.info("Pin %r mode is %r", pin_num, 1)
            logging.info("Pin %r state is %r", pin_num, state)
            self.gpio_map[pin_key]['mode'] = 1
        else:
            wiringpi.pinMode(pin_num, wiringpi.GPIO.OUTPUT)
            wiringpi.digitalWrite(pin_num, state)
            self.gpio_map[pin_key]['mode'] = wiringpi.GPIO.OUTPUT
        self.gpio_map[pin_key]['state'] = state

    def _get_pin_num_and_key(self, arg):
        pin_num = None
        pin_key = None
        if arg in self.gpio_map:
            pin_num = self.gpio_map[arg]['pin']
        else:
            for val in self.gpio_map.values():
                if val['name'] == arg:
                    pin_num = val['pin']
                    break
            if pin_num is None:
                pin_num = int(arg)
        for key, val in self.gpio_map.items():
            if val['pin'] == pin_num:
                pin_key = key
                break
        return pin_num, pin_key

    @staticmethod
    def do_exit(arg):
        """I mean it should be obvious

        Usage:
            exit
        """
        arg = arg
        return True


def _exit_cmd_loop():
    if readline:
        try:
            readline.write_history_file()
        except IOError:
            pass


def main():
    """Main program"""
    parser = argparse.ArgumentParser()

    log_levels = ('debug', 'info', 'warning', 'error', 'fatal', 'critical')
    parser.add_argument('--loglevel', '-l', choices=log_levels, default='info',
                        help='Python logger log level')
    parser.add_argument('--pin_config_path', '-pp',
                        help="Path to the pin config",
                        default=None)
    parser.add_argument('--pin_config_filename', '-pf',
                        help="Filename of config",
                        default='bph_pinout_v2c.json')
    parser.add_argument('--init_state', '-is',
                        help='Initialize pins on startup',
                        default=False, action='store_true')
    pargs = parser.parse_args()

    logging.basicConfig(level=getattr(logging, pargs.loglevel.upper()))
    logging.debug("asdf")
    try:
        BphShell(pargs.pin_config_path,
                 pargs.pin_config_filename,
                 pargs.init_state).cmdloop()
        _exit_cmd_loop()
    except KeyboardInterrupt:

        _exit_cmd_loop()


if __name__ == '__main__':
    main()
