from telegram.ext import Application, CommandHandler, MessageHandler, filters

from tresrv.config import load_settings
from tresrv.db import make_session_factory
from tresrv.bot.onboarding import build_onboarding_handler
from tresrv.bot.profile import profil_command, cel_command
from tresrv.bot.weight import waga_command
from tresrv.bot.meals import text_message_handler, photo_message_handler
from tresrv.llm import GeminiClient


def build_application() -> Application:
    settings = load_settings()
    session_factory = make_session_factory(settings.database_url)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["session_factory"] = session_factory
    application.bot_data["settings"] = settings
    application.bot_data["llm_client"] = GeminiClient(api_key=settings.gemini_api_key)
    application.add_handler(build_onboarding_handler())
    application.add_handler(CommandHandler("profil", profil_command))
    application.add_handler(CommandHandler("cel", cel_command))
    application.add_handler(CommandHandler("waga", waga_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
