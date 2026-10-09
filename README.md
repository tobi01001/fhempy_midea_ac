# fhempy_midea_ac

This repository contains the Midea air-conditioner module for
[fhempy](https://github.com/fhempy/fhempy) and is its development source.
FHEM users receive fhempy modules from the fhempy repository, not directly from
this repository.

## Module files

- `manifest.json` — module metadata used by fhempy.
- `midea_ac.py` — the Midea air-conditioner module implementation.

Keep the manifest and implementation in sync when changing module metadata or
behavior. Include relevant usage, configuration, and compatibility notes with
changes that affect users.

## FHEM installation and usage

The current fhempy documentation describes installing modules from the
fhempy repository through its FHEM update control file. It does not document a
supported external-repository URL or custom module path. As a result, this
repository alone does not make `midea_ac` available through `update all`; the
module must first be contributed to fhempy. No upstream pull request is being
created as part of this work.

Once the module has been merged into fhempy, define it with the device IP,
device ID, token, and key:

```text
define <name> fhempy midea_ac <ip> <device_id> <token> <key>
```

fhempy installs the `msmart-ng` requirement from the module manifest
automatically. The module supports these attributes:

- `interval` — polling interval in seconds (default `60`).
- `maxBackoff` — maximum retry delay while the device is unreachable (default
  `600` seconds).
- `disable` — set to `1` to stop all network activity (default `0`).

To install or update fhempy modules, use the standard fhempy update source:

```text
update add https://raw.githubusercontent.com/fhempy/fhempy/master/controls_pythonbinding.txt
update
update all
shutdown restart
```

The module will be available through that update source only after it has been
added to fhempy and included in its update control file.

## Development and releases

Develop and test changes in this repository. Use semantic versions and keep
`manifest.json`'s `version` in sync with `__version__` in `midea_ac.py`. The
existing version workflow bumps the patch version on merges to `main` unless
the version was explicitly changed; create a matching `vX.Y.Z` tag and GitHub
release when publishing a release.

Releases do not automatically propagate to FHEM. For each release, the module
must also be contributed to fhempy under
`FHEM/bindings/python/fhempy/lib/midea_ac/` (with the module code, package
initializer, and `manifest.json`). After the upstream change is merged and
included in fhempy's update control file, users receive it through the normal
FHEM update process above. Confirm with fhempy maintainers whether that control
file is generated or needs to be changed in the upstream contribution.

## Availability handling

The AC is a mobile device and is not always reachable.

- Network failures are handled with an exponential back-off (`interval` doubled per consecutive failure, capped by attribute `maxBackoff`, default 600s). While unreachable, `state`/`online` are `offline`; the connection is re-established automatically.
- Attribute `disable` (`0`/`1`): when `1`, the module has no network activity at all and `state` is `disabled`.
- `set <name> disable` / `set <name> enable` set the `disable` attribute at runtime (without saving the config).
