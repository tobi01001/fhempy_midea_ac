import asyncio
import logging
import traceback
from fhempy.lib import fhem
from fhempy.lib.generic import FhemModule
from msmart.device.AC.device import AirConditioner as AC

__version__ = "1.0.0"



class midea_ac(FhemModule):
    def __init__(self, logger):
        super().__init__(logger)
        self.device = None
        self.hash = None
        self._network_busy = False
        self._connected = False
        self._fail_count = 0
        self._loop_task = None
        self._wake = asyncio.Event()
        self._attr_interval = 60
        self._attr_disable = 0
        self.logger.info("Midea_AC: [DEBUG] __init__ aufgerufen.")
        # Basis-Setliste für den Start
        self._set_list = {
            "on": {"args": []},
            "off": {"args": []},
            "desiredTemp": {"args": ["temperature"], "options": "slider,17,1,30"},
            "mode": {"args": ["mode"], "options": "AUTO,COOL,DRY,FAN_ONLY"},
            "fanSpeed": {"args": ["speed"], "options": "AUTO,LOW,MEDIUM,HIGH"},
            "power": {"args": ["state"], "options": "on,off"},
            "enable": {"args": []},
            "disable": {"args": []},
        }

    async def Define(self, hash, args, argsh):
        self.logger.info("Midea_AC: [DEBUG] Define gestartet.")
        self.hash = hash
        try:
            await self.set_set_config(self._set_list)
            
            if len(args) < 7:
                await fhem.readingsSingleUpdate(self.hash, "state", "error: Parameter fehlen", 1)
                return

            self.ip = args[3]
            self.dev_id = int(args[4])
            self.token = args[5]
            self.key = args[6]
            self.port = 6444

            await self.set_attr_config({
                "interval": {"default": 60, "format": "int", "help": "Polling interval in seconds (default 60)."},
                "disable": {"default": 0, "format": "int",
                            "help": "Set to 1 to disable the module: no network activity at all."},
                "maxBackoff": {"default": 600, "format": "int",
                               "help": "Maximum polling delay in seconds while the device is unreachable (default 600)."},
            })

            self.device = AC(ip=self.ip, port=self.port, device_id=self.dev_id)
            await self._evaluate_capabilities()

            # Hintergrund-Loop starten (verbindet selbst, sobald aktiv)
            self._loop_task = self.create_async_task(self._update_loop())
            if self._is_disabled():
                await self._set_disabled_state()
            else:
                await fhem.readingsSingleUpdate(self.hash, "state", "connecting", 1)

        except Exception as e:
            self.logger.error(f"Midea_AC [CRASH] in Define: {e}\n{traceback.format_exc()}")

    async def _evaluate_capabilities(self):
        dynamic_setters = {
            "on": {"args": []},
            "off": {"args": []},
            "desiredTemp": {"args": ["temperature"], "options": "slider,17,1,30"},
            "power": {"args": ["state"], "options": "on,off"},
            "enable": {"args": []},
            "disable": {"args": []},
        }

        if hasattr(self.device, "supported_operation_modes") and self.device.supported_operation_modes:
            modes = [m.name.upper() for m in self.device.supported_operation_modes]
            dynamic_setters["mode"] = {"args": ["mode"], "options": ",".join(modes)}

        if hasattr(self.device, "supported_fan_speeds") and self.device.supported_fan_speeds:
            speeds = [s.name.upper() for s in self.device.supported_fan_speeds]
            dynamic_setters["fanSpeed"] = {"args": ["speed"], "options": ",".join(speeds)}

        if hasattr(self.device, "supported_swing_modes") and self.device.supported_swing_modes:
            swings = [sw.name.upper() for sw in self.device.supported_swing_modes]
            if len(swings) > 1:
                dynamic_setters["swingMode"] = {"args": ["swing"], "options": ",".join(swings)}
        
        if getattr(self.device, "supports_display_control", False):
            dynamic_setters["display"] = {"args": ["state"], "options": "on,off"}

        self._set_list = dynamic_setters
        await self.set_set_config(self._set_list)

    def _is_disabled(self):
        try:
            return int(self._attr_disable) == 1
        except (TypeError, ValueError):
            return False

    async def _set_disabled_state(self):
        await fhem.readingsBeginUpdate(self.hash)
        await fhem.readingsBulkUpdate(self.hash, "state", "disabled")
        await fhem.readingsBulkUpdate(self.hash, "online", "disabled")
        await fhem.readingsBulkUpdate(self.hash, "debug_status", "disabled")
        await fhem.readingsEndUpdate(self.hash, 1)

    async def set_attr_disable(self, hash):
        if self._is_disabled():
            await self._set_disabled_state()
        else:
            self._connected = False
            self._fail_count = 0
            await fhem.readingsSingleUpdate(self.hash, "state", "connecting", 1)
        self._wake.set()

    async def set_attr_interval(self, hash):
        self._wake.set()

    def _next_delay(self):
        try:
            interval = max(int(self._attr_interval), 1)
        except (TypeError, ValueError):
            interval = 60
        if self._fail_count == 0:
            return interval
        try:
            max_backoff = max(int(self._attr_maxBackoff), interval)
        except (AttributeError, TypeError, ValueError):
            max_backoff = 600
        return min(interval * (2 ** min(self._fail_count, 10)), max_backoff)

    async def _connect(self):
        await self.device.authenticate(token=self.token, key=self.key)
        await asyncio.wait_for(self.device.get_capabilities(), timeout=5.0)
        await self._evaluate_capabilities()
        self._connected = True

    async def _handle_failure(self, ex):
        self._connected = False
        self._fail_count += 1
        self.logger.warning(
            f"Midea_AC: Gerät nicht erreichbar (Fehler #{self._fail_count}): {ex!r}; "
            f"nächster Versuch in {self._next_delay()}s")
        if self._fail_count == 1 or self._fail_count % 5 == 0:
            await fhem.readingsBeginUpdate(self.hash)
            await fhem.readingsBulkUpdate(self.hash, "state", "offline")
            await fhem.readingsBulkUpdate(self.hash, "online", "offline")
            await fhem.readingsBulkUpdate(self.hash, "debug_status", f"Offline (Fehler: {self._fail_count})")
            await fhem.readingsEndUpdate(self.hash, 1)

    async def _poll_once(self):
        """One poll cycle. The caller guarantees the module is enabled."""
        if self._network_busy:
            self.logger.info("Midea_AC: [LOOP] Netzwerk belegt durch Setter. Überspringe Intervall.")
            return
        try:
            self._network_busy = True
            if not self._connected:
                await self._connect()
            await asyncio.wait_for(self.device.refresh(), timeout=4.0)
            if getattr(self.device, "online", True) is False:
                raise ConnectionError("Gerät antwortet nicht")
            if self._fail_count:
                self.logger.info("Midea_AC: Gerät wieder erreichbar.")
            self._fail_count = 0
            await self._update_readings()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._handle_failure(e)
        finally:
            self._network_busy = False

    async def _update_loop(self):
        first = True
        while True:
            if self._is_disabled():
                # keine Aktivität: warten bis Attribut/Set uns weckt
                self._wake.clear()
                await self._wake.wait()
                first = True
                continue

            if not first:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._next_delay())
                    # geweckt (Attribut/Set geändert): Zustand neu bewerten
                    continue
                except asyncio.TimeoutError:
                    pass
                if self._is_disabled():
                    continue
            first = False

            logging.getLogger("msmart").setLevel(self.logger.getEffectiveLevel())
            await self._poll_once()

    async def _update_readings(self):
        def get_enum_name(obj):
            return obj.name if hasattr(obj, "name") else str(obj)

        try:
            display_state = "off"
            if hasattr(self.device, "display_on"):
                display_state = "on" if self.device.display_on else "off"
            elif hasattr(self.device, "display"):
                display_state = "on" if self.device.display else "off"

            await fhem.readingsBeginUpdate(self.hash)
            await fhem.readingsBulkUpdate(self.hash, "state", "on" if self.device.power_state else "off")
            await fhem.readingsBulkUpdate(self.hash, "power", "on" if self.device.power_state else "off")
            await fhem.readingsBulkUpdate(self.hash, "temperature", self.device.indoor_temperature)
            await fhem.readingsBulkUpdate(self.hash, "desiredTemp", self.device.target_temperature)
            await fhem.readingsBulkUpdate(self.hash, "mode", get_enum_name(self.device.operational_mode))
            await fhem.readingsBulkUpdate(self.hash, "fanSpeed", get_enum_name(self.device.fan_speed))
            
            if "swingMode" in self._set_list:
                await fhem.readingsBulkUpdate(self.hash, "swingMode", get_enum_name(self.device.swing_mode))
            if "display" in self._set_list:
                await fhem.readingsBulkUpdate(self.hash, "display", display_state)
                
            await fhem.readingsBulkUpdate(self.hash, "online", "online")
            await fhem.readingsEndUpdate(self.hash, 1)
        except Exception as e:
            self.logger.error(f"Midea_AC: Readings-Update-Fehler: {e}")

    # --- Zentraler, asynchroner Worker (Vollkommen entkoppelt von FHEM) ---
    async def _execute_set_command(self, cmd_type, value):
        if self._is_disabled():
            self.logger.info(f"Midea_AC: Modul deaktiviert, ignoriere {cmd_type}")
            return
        self.logger.info(f"Midea_AC: [SET-WORKER] Starte asynchrone Verarbeitung: {cmd_type} -> {value}")
        
        # Falls das Netzwerk durch den Loop belegt ist, kurz warten (max 3 Sek)
        for _ in range(30):
            if not self._network_busy:
                break
            await asyncio.sleep(0.1)

        if self._is_disabled():
            return
        self._network_busy = True
        try:
            if not self._connected:
                await self._connect()
            if cmd_type == "power":
                self.device.power_state = (value == "on")
            elif cmd_type == "desiredTemp":
                self.device.target_temperature = float(value)
            elif cmd_type == "mode":
                mode_enum = type(self.device.operational_mode)
                self.device.operational_mode = mode_enum[value.upper()]
            elif cmd_type == "fanSpeed":
                fan_enum = type(self.device.fan_speed)
                self.device.fan_speed = fan_enum[value.upper()]
            elif cmd_type == "swingMode":
                swing_enum = type(self.device.swing_mode)
                self.device.swing_mode = swing_enum[value.upper()]
            elif cmd_type == "display":
                if hasattr(self.device, "display"):
                    self.device.display = (value == "on")
                else:
                    self.device.display_on = (value == "on")

            self.logger.info(f"Midea_AC: [SET-WORKER] Sende .apply() an Hardware...")
            await asyncio.wait_for(self.device.apply(), timeout=5.0)
            
            # Das von dir gewünschte Verarbeitungs-Delay für die Hardware
            self.logger.info(f"Midea_AC: [SET-WORKER] .apply() abgesetzt. Warte 0.6s Verarbeitungszeit...")
            await asyncio.sleep(0.6)
            
            # Sofortige Verifizierung abfragen
            self.logger.info(f"Midea_AC: [SET-WORKER] Triggere Verifizierungs-Refresh...")
            await asyncio.wait_for(self.device.refresh(), timeout=4.0)
            
            self.logger.info(f"Midea_AC: [SET-WORKER] Refresh erhalten. Aktualisiere FHEM-Readings.")
            self._fail_count = 0
            await self._update_readings()
            await fhem.readingsSingleUpdate(self.hash, "debug_status", "Bereit", 1)

        except Exception as e:
            await self._handle_failure(e)
            self.logger.error(f"Midea_AC: [SET-WORKER-ERROR] Fehler bei {cmd_type}: {e}\n{traceback.format_exc()}")
            await fhem.readingsSingleUpdate(self.hash, "debug_status", f"Fehler bei set_{cmd_type}", 1)
        finally:
            self._network_busy = False
    
    async def _set_disable_attr(self, value):
        # Attribut ohne "save"-Pflicht setzen (kein 'save' ausgeführt)
        await fhem.CommandAttr(self.hash, f"{self.hash['NAME']} disable {value}")

    async def set_enable(self, hash, params):
        self.logger.info("Midea_AC: [FHEM-SET] set enable")
        await self._set_disable_attr(0)
        return ""

    async def set_disable(self, hash, params):
        self.logger.info("Midea_AC: [FHEM-SET] set disable")
        await self._set_disable_attr(1)
        return ""

    async def set_on(self, hash, params):
        self.logger.info("Midea_AC: [FHEM-SET] set on")
        self.create_async_task(self._execute_set_command("power", "on"))
        return ""

    async def set_off(self, hash, params):
        self.logger.info("Midea_AC: [FHEM-SET] set off")
        self.create_async_task(self._execute_set_command("power", "off"))
        return ""
    
    # --- Setter (Geben FHEM die Kontrolle SOFORT in < 1ms zurück) ---
    async def set_power(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set power {params['state']}")
        self.create_async_task(self._execute_set_command("power", params["state"]))
        return ""

    async def set_desiredTemp(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set desiredTemp {params['temperature']}")
        self.create_async_task(self._execute_set_command("desiredTemp", params["temperature"]))
        return ""

    async def set_mode(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set mode {params['mode']}")
        self.create_async_task(self._execute_set_command("mode", params["mode"]))
        return ""

    async def set_fanSpeed(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set fanSpeed {params['speed']}")
        self.create_async_task(self._execute_set_command("fanSpeed", params["speed"]))
        return ""

    async def set_swingMode(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set swingMode {params['swing']}")
        self.create_async_task(self._execute_set_command("swingMode", params["swing"]))
        return ""

    async def set_display(self, hash, params):
        self.logger.info(f"Midea_AC: [FHEM-SET] set display {params['state']}")
        self.create_async_task(self._execute_set_command("display", params["state"]))
        return ""