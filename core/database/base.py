from typing import TYPE_CHECKING, Optional, Union, Self

from tortoise.models import Model

from core.exports import exports

if TYPE_CHECKING:
    from core.builtins.bot import Bot


class DBModel(Model):
    """
    Base model for all database models.
    """

    class Meta:
        abstract = True

    @classmethod
    async def get_by_target_id(cls,
                               target_id: Union["Bot.MessageSession", "Bot.FetchedMessageSession", str],
                               create: bool = True
                               ) -> Optional[Self]:
        """
        Get a model by target_id.

        :param target_id: The target_id to search for.
        :param create: Whether to create a new model if it doesn't exist.
        :return: The model instance. If create is True and the model doesn't exist, a new instance will be created, otherwise None.

        """
        t = None
        if isinstance(target_id, str):
            t = target_id
        else:
            if ex := exports.get("Bot"):
                ex: 'Bot'
                if isinstance(target_id, (ex.MessageSession, ex.FetchedMessageSession)):
                    t = target_id.session_info.target_id
        if not t:
            raise ValueError(
                "target_id must be a str or a MessageSession/FetchedMessageSession instance, or exports are unavailable.")
        if create:
            return (await cls.get_or_create(target_id=t))[0]
        return await cls.get_or_none(target_id=t)

    @classmethod
    async def get_by_sender_id(cls,
                               sender_id: Union["Bot.MessageSession", "Bot.FetchedMessageSession", str],
                               create: bool = True
                               ) -> Optional[Self]:
        """
        Get a model by sender_id.

        :param sender_id: The sender_id to search for.
        :param create: Whether to create a new model if it doesn't exist.
        :return: The model instance. If create is True and the model doesn't exist, a new instance will be created, otherwise None.
        """
        t = None
        if isinstance(sender_id, str):
            t = sender_id
        else:
            if ex := exports.get("Bot"):
                ex: 'Bot'
                if isinstance(sender_id, (ex.MessageSession, ex.FetchedMessageSession)):
                    t = sender_id.session_info.sender_id
        if not t:
            raise ValueError(
                "sender_id must be a str or a MessageSession/FetchedMessageSession instance, or exports are unavailable.")
        if create:
            return (await cls.get_or_create(sender_id=t))[0]
        return await cls.get_or_none(sender_id=t)
