# `/profile/` Mumble Panel Wireframe

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This document reflects the current rendered FG `/profile/` Mumble panel, not the older
server-selector sketch.

## One server, one eligible pilot

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Server      Finland                                              |
| Display Name [ALLY CORP] Pilot Main                              |
| Username    pilot_main                                           |
| Address    voice.example.org                                     |
| Port       64738                                                 |
| IsAdmin    Yes                                                   |
|                                                                  |
| [Reset Password]                                                 |
| status: Password reset requested <generated-password>            |
|                                                                  |
| [Custom password (min 8)____________________] [Set Password]     |
+------------------------------------------------------------------+
```

## One server, multiple eligible pilots

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Server      Finland                                              |
| Display Name [ALLY CORP] Pilot Main                              |
| Username    pilot_main                                           |
| Address     voice.example.org                                    |
| Port        64738                                                |
|                                                                  |
| Mumble Authentication [ Pilot Main v ]                           |
|                                                                  |
| [Reset Password]                                                 |
| status: -                                                        |
|                                                                  |
| [Custom password (min 8)____________________] [Set Password]     |
+------------------------------------------------------------------+
```

## BG unavailable

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Server      Mumble Authentication                                |
| Display Name [ALLY CORP] Pilot Main                              |
| Username    [ALLY CORP] Pilot Main                               |
| Address     BG unavailable                                       |
| Port        -                                                    |
|                                                                  |
| [Reset Password disabled]                                        |
|                                                                  |
| [Custom password (min 8)____________________] [Set Password dis.]|
+------------------------------------------------------------------+
```

Notes:

- Current implementation renders one panel per available BG server.
- The `Server` value is fixed text from the BG server name/label, not a live dropdown.
- When more than one eligible pilot is available, FG shows a `Mumble Authentication` selector for pilot choice.
- `Display Name` and `Username` are both shown.
- `IsAdmin` is shown only when true.
- If BG is unavailable, `Address` shows `BG unavailable` and password actions are disabled.
