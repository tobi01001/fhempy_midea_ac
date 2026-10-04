# fhempy_midea_ac

This repository contains the Midea air-conditioner module for
[fhempy](https://github.com/fhempy/fhempy). It is intended to store, distribute,
and further develop the module.

## Module files

- `manifest.json` — module metadata used by fhempy.
- `midea_ac.py` — the Midea air-conditioner module implementation.

Keep the manifest and implementation in sync when changing module metadata or
behavior. Include relevant usage, configuration, and compatibility notes with
changes that affect users.

## Development

Make changes to the module and its manifest in this repository so it can be
maintained and developed independently.

## Availability handling

The AC is a mobile device and is not always reachable.

- Network failures are handled with an exponential back-off (`interval` doubled per consecutive failure, capped by attribute `maxBackoff`, default 600s). While unreachable, `state`/`online` are `offline`; the connection is re-established automatically.
- Attribute `disable` (`0`/`1`): when `1`, the module has no network activity at all and `state` is `disabled`.
- `set <name> disable` / `set <name> enable` set the `disable` attribute at runtime (without saving the config).
