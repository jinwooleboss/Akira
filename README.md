# Planning Bot — Bot Telegram

Bot Telegram qui génère l'image "PLANNING - Les sorties animes du ..." via la
commande `/createplanning`.

## Variables d'environnement à configurer sur l'hébergeur (Railway, etc.)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Le token donné par @BotFather |
| `ADMIN_ID` | Ton ID Telegram (obtenu via la commande `/id` une fois le bot lancé) |

**Ne jamais écrire ces valeurs dans le code ou les commiter sur GitHub.**

## Commandes du bot

- `/createplanning` — démarre la création d'un planning
- `/id` — affiche ton ID Telegram
- `/autoriser <id>` — (admin) autorise un utilisateur
- `/revoquer <id>` — (admin) révoque un utilisateur
- `/utilisateurs` — (admin) liste les utilisateurs autorisés
- `/annuler` — annule une création en cours

## Structure

```
bot.py              # Tout le bot (conversation + génération d'image)
requirements.txt     # Dépendances Python
Procfile              # Commande de démarrage pour Railway
fonts/                # Polices Poppins Bold/Medium (nécessaires)
logos/                # Logos PNG optionnels des plateformes
```