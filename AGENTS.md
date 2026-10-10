# Projektregeln

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
