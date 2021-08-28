import logging
from datetime import datetime, timedelta
from math import ceil
from typing import List

import telegram
from telegram import Message, Update
from telegram.ext import (CallbackContext, CommandHandler, Dispatcher,
                          MessageHandler, Updater)
from telegram.ext.filters import Filters

from setting import CHATS, DEFAULT_LIFE_TIME, TOKEN

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)


def delete_message(context: CallbackContext, chat_id, message_id):
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except telegram.error.BadRequest as e:
        logger.exception("DELETE MESSAGE %s IN CHAT %s ERROR", message_id, chat_id)


def get_job_name(child, parent="root"):
    return f"{parent}_{child}"


def start(update: Update, context: CallbackContext) -> None:
    """Sends explanation on how to use the bot."""
    message = f"""Hi! All messages in this group will be deleted after {DEFAULT_LIFE_TIME} seconds.
Run a command by reply any message.
/set <seconds> to set a custom scheduler.
/unset to remove exist scheduler
    """
    update.message.reply_text(message)


def purge_message(context: CallbackContext) -> None:
    """Send the alarm message."""
    job = context.job
    if not job:
        return
    data = job.context
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if not chat_id or not message_id:
        logger.error("[Purge message] Missing params")
        return
    delete_message(context, chat_id, message_id)


def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    if not context.job_queue:
        return True

    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
        job_context = job.context
        if job_context:
            chat_id = job_context.get("chat_id")
            message_id = job_context.get("message_id")
            if not chat_id or not message_id:
                logger.error("[Remove jobs] Invalid job context")
                continue
            is_child_message = job_context.get("is_child_message", False)
            if is_child_message:
                delete_message(context, chat_id, message_id)
                continue
            else:
                children = job_context.get("children", [])
                if not children:
                    continue
                for child in children:
                    remove_job_if_exists(get_job_name(child, message_id), context)
    return True


def set_timer(
    context: CallbackContext,
    message: Message,
    due: int,
    children: List[Message] = None,
    show_response: bool = False,
) -> None:
    if not children:
        children = []
    delete_at = datetime.utcnow() + timedelta(seconds=due)
    job_removed = remove_job_if_exists(get_job_name(message.message_id), context)

    chat_id = message.chat_id
    if context.job_queue:
        children_ids = []
        for child in children:
            children_ids.append(child.message_id)
            context.job_queue.run_once(
                purge_message,
                delete_at,
                context={
                    "chat_id": chat_id,
                    "message_id": child.message_id,
                    "is_child_message": True,
                },
                name=get_job_name(child.message_id, message.message_id),
            )
        if show_response:
            text = f"This message will delete after {due} second(s)"
            if job_removed:
                text = f"Old timer was removed. {text}"
            bot_message: Message = message.reply_text(text)
            context.job_queue.run_once(
                purge_message,
                delete_at,
                context={
                    "chat_id": chat_id,
                    "message_id": bot_message.message_id,
                    "is_child_message": True,
                },
                name=get_job_name(bot_message.message_id, message.message_id),
            )
            children_ids.append(bot_message.message_id)
        context.job_queue.run_once(
            purge_message,
            delete_at,
            context={
                "chat_id": chat_id,
                "message_id": message.message_id,
                "children": children_ids,
            },
            name=get_job_name(message.message_id),
        )


def set_timer_from_command(update: Update, context: CallbackContext):
    command_message: Message = update.message
    root_message: Message = command_message.reply_to_message

    if not root_message:
        update.message.reply_text(
            "You have to reply the message which you want to schedule delete"
        )
        return

    if not context.args:
        update.message.reply_text("Missing params!, send /help for more information")
        return

    # args[0] should contain the time for the timer in seconds
    due = int(context.args[0])
    if due < 0:
        update.message.reply_text("Sorry we can not go back to future!")
        return
    due = ceil(due)

    set_timer(context, message=root_message, due=due, children=[command_message], show_response=True)


def default_set_timer(update: Update, context: CallbackContext):
    set_timer(context, message=update.message, due=DEFAULT_LIFE_TIME)


def unset(update: Update, context: CallbackContext) -> None:
    """Remove the job if the user changed their mind."""
    chat_id = update.message.chat_id
    job_name = get_job_name(update.message.reply_to_message.message_id)
    removed = remove_job_if_exists(job_name, context)
    if context.job_queue and removed:
        delete_message(context, chat_id, update.message.message_id)


def main() -> None:
    """Run bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(TOKEN)

    # Get the dispatcher to register handlers
    dispatcher: Dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    default_filters = Filters.chat(chat_id=CHATS)
    dispatcher.add_handler(CommandHandler("start", start, filters=default_filters))
    dispatcher.add_handler(CommandHandler("help", start, filters=default_filters))
    dispatcher.add_handler(CommandHandler("set", set_timer_from_command, filters=default_filters))
    dispatcher.add_handler(MessageHandler(default_filters, default_set_timer))
    dispatcher.add_handler(CommandHandler("unset", unset, filters=default_filters))

    # Start the Bot
    updater.start_polling()

    # Block until you press Ctrl-C or the process receives SIGINT, SIGTERM
    # SIGABRT. This should be used most of the time, since start_polling() is
    # non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == "__main__":
    main()
