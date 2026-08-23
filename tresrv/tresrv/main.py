from telegram.ext import Application, CommandHandler

from tresrv.config import load_settings
from tresrv.db import make_session_factory
from tresrv.bot.onboarding import build_onboarding_handler
from tresrv.bot.profile import profil_command, cel_command
from tresrv.bot.weight import waga_command


def build_application() -> Application:
    settings = load_settings()
    session_factory = make_session_factory(settings.database_url)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["session_factory"] = session_factory
    application.bot_data["settings"] = settings
    application.add_handler(build_onboarding_handler())
    application.add_handler(CommandHandler("profil", profil_command))
    application.add_handler(CommandHandler("cel", cel_command))
    application.add_handler(CommandHandler("waga", waga_command))
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
