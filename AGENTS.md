# Projektregeln

## Laufende Capture-Diagnose

Vor Aussagen oder Änderungen zu Frameverlusten, beschädigten MJPEG-Puffern,
V4L2, UVC, USB, Preview oder Aufnahme zuerst
[`docs/CAPTURE_DIAGNOSIS.md`](docs/CAPTURE_DIAGNOSIS.md) vollständig lesen.
Der dort dokumentierte Belegstand, die bereits ausgeschlossenen Erklärungen
und die offenen A/B-Tests sind verbindlich. Bereits erledigte Prüfungen nicht
ohne neue Evidenz wiederholen und offene Hypothesen nicht als Ursache
darstellen. Einzelereignisse, einzelne Vorher-/Nachher-Läufe und ein einmaliger
Tausch zwischen den Kameras dürfen weder als Referenz noch als Ursachen- oder
Wirksamkeitsbeleg verwendet werden. Wiederholte, alternierende Kreuztests sind
zulässig; unbekannte Schwankungen zwischen Kameras oder Zeitfenstern dürfen
dabei nicht dem Testparameter zugerechnet werden. Neue belastbare Erkenntnisse
in diesem Dokument ergänzen.

## Nichtinteraktiver SSH-Zugriff auf die Kamera-Pis

Für SSH-Kommandos an `kaderblick@192.168.178.47` und
`kaderblick@192.168.178.48` ausschließlich dieses Muster verwenden:

```bash
env -u DISPLAY -u WAYLAND_DISPLAY \
  SSH_ASKPASS=/bin/false SSH_ASKPASS_REQUIRE=never \
  sshpass -p 'kaderblick' ssh -T \
  -o IdentityAgent=none \
  -o IdentitiesOnly=yes \
  -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password \
  -o KbdInteractiveAuthentication=no \
  -o NumberOfPasswordPrompts=1 \
  -o ConnectTimeout=5 \
  -o ConnectionAttempts=1 \
  "kaderblick@<IP>" '<KOMMANDO>' </dev/null
```

- Niemals einen normalen interaktiven `ssh`-Aufruf verwenden.
- Niemals Schlüssel ausprobieren oder den SSH-Agenten verwenden.
- Bei einem Authentifizierungsfehler nicht mit abgewandelten SSH-Aufrufen
  wiederholen, sondern den Fehler berichten.
- Für `sudo` innerhalb des Remote-Kommandos das Passwort über stdin und
  `sudo -S -p ''` übergeben; keinen Dialog öffnen.
