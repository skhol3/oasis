# Odoo19: Chromium headless aborta por ruta de socket

Fecha: 2026-11-10

Los tests de navegador del bundle global `odoo19` fallan porque Chromium headless aborta al arrancar: la ruta de su socket mide 110 bytes y el máximo es 107. La solución es correr los tests con un `TMPDIR` corto.

## Qué pasó

El 10 de noviembre de 2026, entre las 21:40:47 y las 21:43:46, systemd-coredump registró 18 SIGABRT idénticos de `/usr/lib/chromium/chromium`, uno cada ~10 segundos. Cada uno era un Chromium headless que lanzaba un test de navegador (tour) de Odoo.

| Dato | Valor |
| --- | --- |
| Cadena de procesos | `verify-module` → `install-module` → `odoo-bin` (bundle `~/.agents/skills/odoo19/tools/`) |
| Base de datos | `cc_test_corpus_cafe_update` |
| Chromium | 155.0.8059.84-1 |
| Ejemplo de PID | 2574356 |
| Stack | `ChromeMain` → `abort`, hilo principal, al arrancar |

Impacto: todos los tests de navegador de esa corrida fallaron, así que ese resultado de `verify-module` no vale. No se perdieron datos: los perfiles eran temporales.

## Causa

Chromium no puede crear su socket singleton porque la ruta es demasiado larga y aborta a propósito. El mensaje salió de la memoria del core:

```
FATAL:chrome/browser/process_singleton_posix.cc:313] Socket path too long:
/tmp/gpB6f7cC/gachADTC/tmp.bumyjLXJec/tmp/tmp5uwjifu1_chrome_odoo/org.chromium.Chromium.B3vxqV/SingletonSocket
```

- **Probado:** esa ruta mide 110 bytes. La ruta de un socket Unix (`sun_path`) admite como máximo 107 más el NUL.
- **Inferido, sin confirmar:** Odoo arma el perfil `*_chrome_odoo` bajo `tempfile`, o sea, bajo `$TMPDIR`. La sesión que corrió los tests tenía un `TMPDIR` muy anidado (`/tmp/gpB6f7cC/gachADTC/tmp.bumyjLXJec/tmp`), probablemente el temp de un agente o sandbox. El proceso ya había terminado y no se pudo leer su entorno.

## Descartado

- **Falta de memoria:** la RAM estaba justa (474Mi libres, 18Gi de swap en uso), pero el journal no muestra ningún OOM kill.
- **Flags de Omarchy** (`~/.config/chromium-flags.conf`): agregan `--ozone-platform=wayland` y `--load-extension` a esta corrida. Con los mismos flags y una ruta corta, Chromium arrancó bien.
- **Bug de Omarchy o de Chromium:** no lo es, así que no hay nada que reportar upstream.

## Cómo solucionarlo

No se aplicó ningún cambio todavía. Pasos sugeridos:

- [ ] Volver a correr los tests con un temp corto: `TMPDIR=/tmp verify-module --compact <módulos>`
- [ ] Confirmar que no aparecen nuevos cores de Chromium con `coredumpctl list --since "10 min ago"`
- [ ] Para que no vuelva a pasar, exportar `TMPDIR=/tmp` en `~/.agents/skills/odoo19/tools/common.sh` (o acortar el `TMPDIR` del agente que lanza los tests)
- [ ] Guardar este hallazgo en Engram, proyecto `odoo19`, topic `odoo19/browser-tests/chromium-socket-path-too-long`

Diagnóstico rápido si vuelve a pasar: `coredumpctl dump <pid> --output=<archivo>`, después `strings <archivo> | grep FATAL`, y borrar el core al terminar.
