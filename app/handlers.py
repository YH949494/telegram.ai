import logging
import re
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from .classifier import classify_message
except ImportError:
    from .classifier import classify

    def classify_message(text, settings):
        category = classify(text)
        if category in AUTO_REPLY_ALLOWED_CATEGORIES:
            action = "auto_reply"
            confidence = 0.8
        elif category in settings.suggestion_only_categories:
            action = "suggest_only"
            confidence = 0.7
        else:
            action = "ignore"
            confidence = 0.4
        return SimpleNamespace(
            category=category,
            action=action,
            confidence=confidence,
            suggested_reply="",
            reason="rule_fallback",
        )

from .ai_decision import AIDecisionService
from .ai_budget import ai_budget_service
from .ai_reply import AIReplyService
from .config import get_settings
from .db import log_message, log_suggestion, log_feedback, get_few_shot_examples
from .openai_client import OpenAIClient
from .reply_policy import ReplyPolicyService, SEED_REPLIES
from .responses import generate_reply, get_reaction, RESPONSES
from .seed_rotation import seed_rotation_service
from .throttle import auto_reply_throttle, reaction_cooldown

logger = logging.getLogger(__name__)
AUTO_REPLY_ALLOWED_CATEGORIES = {"comeback_campaign", "new_user", "win_share", "loss_share", "positive_signal", "voucher_subscription"}
_ai_runtime = None
RECOMMENDATION_PATTERNS = [r"\brecommend(?:ed|ation)?\b", r"max\s*win", r"this\s+game\s+has", r"daily\s+recommendation", r"推荐", r"建议"]
RESULT_PATTERNS = [r"\bi\s+won\b", r"\bmy\s+win\b", r"\bcashed?\s*out\b", r"\bjackpot\b", r"\bwon\s+\d+(?:\.\d+)?x?\b", r"中奖", r"赢了"]
SUPPORT_PATTERNS = [r"\bvoucher\b", r"\bpromo\b", r"\bissue\b", r"\berror\b", r"\bcan't\b", r"无法", r"失败"]
NEW_USER_PATTERNS = [r"\bi'?m\s+new\b", r"\bi\s+am\s+new\b", r"\bjust\s+joined\b", r"\bnew\s+(?:here|member)\b", r"新人", r"新来的?", r"刚加入"]


def _prepare_reply_payload(payload, allow_button: bool = False):
    if isinstance(payload, dict):
        reply_text = payload.get("text") or ""
        reply_markup = None
        if allow_button:
            button_text = payload.get("button_text")
            button_url = payload.get("button_url")
            if button_text and button_url:
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text=button_text, url=button_url)]]
                )
        return reply_text, reply_markup
    return payload or "", None


async def safe_add_reaction(
    *,
    bot,
    chat_id: int,
    message_id: int,
    emoji: str,
    flow: str,
) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        logger.warning(
            "Failed to add reaction chat_id=%s message_id=%s flow=%s emoji=%s",
            chat_id,
            message_id,
            flow,
            emoji,
            exc_info=True,
        )


def _build_ai_services(settings):
    client = OpenAIClient(api_key=settings.openai_api_key)
    return (
        client,
        AIDecisionService(client=client, model=settings.openai_decision_model),
        AIReplyService(client=client, model=settings.openai_generation_model),
        ReplyPolicyService(
            confidence_threshold=settings.ai_decision_confidence_threshold,
            generation_allowed_categories=settings.ai_generation_allowed_categories,
            seed_only_categories=settings.ai_seed_only_categories,
        ),
    )


def _get_ai_runtime(settings):
    global _ai_runtime
    if _ai_runtime is not None:
        return _ai_runtime
    if not settings.enable_ai_decision or not settings.openai_api_key:
        return None
    _ai_runtime = _build_ai_services(settings)
    return _ai_runtime


def _detect_text_features(text: str):
    lowered = (text or "").lower()
    has_recommendation = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in RECOMMENDATION_PATTERNS)
    has_result = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in RESULT_PATTERNS)
    has_support = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in SUPPORT_PATTERNS)
    has_new_user = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in NEW_USER_PATTERNS)
    return {
        "has_recommendation": has_recommendation,
        "has_result": has_result,
        "has_support": has_support,
        "has_new_user": has_new_user,
        "mixed_signal": has_recommendation and has_result,
    }


def has_mixed_intent(text: str) -> bool:
    return bool(_detect_text_features(text)["mixed_signal"])


def should_run_ai_decision(*, settings, text: str, rule_category: str, rule_confidence: float) -> bool:
    if not settings.enable_ai_decision or not settings.openai_api_key:
        return False
    if rule_category == "unknown":
        return True
    if rule_category in {"new_user", "voucher_question", "support_issue"} and rule_confidence >= 0.9:
        return False
    features = _detect_text_features(text)
    if rule_category == "win_share" and features["mixed_signal"]:
        return True
    if rule_confidence < settings.ai_rule_threshold:
        return True
    if rule_category in set(settings.ai_ambiguous_categories):
        return True
    return False


def _should_run_ai_decision(*, settings, category: str, confidence: float, text: str) -> bool:
    return should_run_ai_decision(
        settings=settings,
        text=text,
        rule_category=category,
        rule_confidence=confidence,
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not getattr(message, "text", None):
        return
    if message.from_user and message.from_user.is_bot:
        return
    if context.bot and message.from_user and context.bot.id == message.from_user.id:
        return

    settings = get_settings()
    text = message.text

    logger.info(
        "Received message chat_id=%s message_id=%s user_id=%s snippet=%s",
        message.chat_id,
        message.message_id,
        message.from_user.id if message.from_user else None,
        text[:80],
    )

    if not settings.enable_tagging:
        logger.info("Tagging disabled; skipping classification")
        return

    decision = classify_message(text, settings)
    category = getattr(decision, "category", "unknown")
    raw_action = getattr(decision, "action", "ignore")
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    suggested_reply = getattr(decision, "suggested_reply", "") or ""
    decision_reason = getattr(decision, "reason", "")

    if confidence < 0.5:
        action = "ignore"
    elif confidence < 0.75:
        action = "suggest_only"
    else:
        action = raw_action

    if action == "auto_reply" and category not in AUTO_REPLY_ALLOWED_CATEGORIES:
        action = "ignore"

    # Stage 2 AI decision only for ambiguous/non-deterministic path.
    ai_path_used = False
    path_used = "deterministic"
    budget_state = "none"
    moderation_state = "none"
    reply_sent = False
    downgrade_applied = False
    category_before = category
    if should_run_ai_decision(settings=settings, text=text, rule_category=category, rule_confidence=confidence):
        ai_path_used = True
        try:
            runtime = _get_ai_runtime(settings)
            if runtime is None:
                raise RuntimeError("ai_runtime_unavailable")
            client, ai_decision_service, ai_reply_service, reply_policy = runtime
            priority = category in set(settings.ai_priority_categories)
            decision_budget = ai_budget_service.allow_decision(
                chat_id=message.chat_id,
                max_per_minute=settings.ai_max_decisions_per_minute,
                max_per_chat_per_hour=settings.ai_max_decisions_per_chat_per_hour,
                priority=priority,
            )
            budget_state = decision_budget.state
            if not decision_budget.allowed:
                decision_reason = f"ai_decision_skipped_due_to_budget:{decision_budget.reason}"
                action = "ignore" if not priority else action
                raise RuntimeError("ai_decision_budget_block")

            few_shot = get_few_shot_examples(category, limit=5) if category != "unknown" else []
            ai_decision = ai_decision_service.decide(text, few_shot_examples=few_shot or None)
            policy = reply_policy.evaluate(ai_decision)
            decision_reason = f"ai:{policy.reason}"
            category = ai_decision.category
            confidence = ai_decision.confidence
            action = "auto_reply" if policy.should_send else "ignore"
            suggested_reply = ""
            path_used = policy.mode
            if action == "ignore":
                logger.info("ai_no_reply_due_to_policy message_id=%s reason=%s", message.message_id, policy.reason)

            if policy.should_send and settings.enable_ai_moderation:
                moderation_input = client.moderate(text)
                if moderation_input:
                    action = "ignore"
                    decision_reason = "ai:moderation_input_block"
                    moderation_state = "input_blocked"
                    logger.info("ai_blocked_by_moderation message_id=%s", message.message_id)
                else:
                    moderation_state = "input_ok"

            selected_seed = None
            if policy.seed_candidates:
                selected_seed = seed_rotation_service.pick_seed(
                    chat_id=message.chat_id,
                    category=policy.category,
                    seeds=policy.seed_candidates,
                    repeat_window_seconds=settings.ai_seed_repeat_window_seconds,
                    max_seed_reuse_per_window=settings.ai_max_seed_reuse_per_window,
                )
                policy.selected_seed = selected_seed

            generation_allowed = (
                action == "auto_reply"
                and policy.should_send
                and policy.mode == "rewrite"
                and settings.enable_ai_generation
                and settings.ai_generation_rewrite_mode
                and selected_seed is not None
            )
            if generation_allowed:
                generation_budget = ai_budget_service.allow_generation(
                    max_per_minute=settings.ai_max_generations_per_minute,
                    allow_downgrade=settings.ai_enable_budget_downgrade,
                    priority=priority,
                )
                budget_state = generation_budget.state
                if generation_budget.state == "downgrade":
                    suggested_reply = selected_seed.text
                    decision_reason = "ai_generation_downgraded_to_seed"
                    path_used = "seed"
                    downgrade_applied = True
                    logger.info("ai_generation_downgraded_to_seed message_id=%s", message.message_id)
                elif not generation_budget.allowed:
                    action = "ignore"
                    decision_reason = f"ai_generation_blocked_due_to_budget:{generation_budget.reason}"
                else:
                    if len((selected_seed.text or "").strip()) < 16:
                        suggested_reply = selected_seed.text
                        path_used = "seed"
                        downgrade_applied = True
                        decision_reason = "ai_generation_short_seed_fallback_to_seed"
                    else:
                        try:
                            ai_reply = ai_reply_service.generate(
                                decision=ai_decision,
                                user_text=text,
                                seed_text=selected_seed.text,
                                max_chars=settings.ai_max_reply_chars,
                            )
                        except Exception:
                            logger.exception("AI rewrite generation failed; falling back to seed message_id=%s", message.message_id)
                            suggested_reply = selected_seed.text
                            path_used = "seed"
                            downgrade_applied = True
                            decision_reason = "ai_generation_error_fallback_to_seed"
                        else:
                            if ai_reply:
                                if settings.enable_ai_moderation:
                                    moderation_reply = client.moderate(ai_reply)
                                    if moderation_reply:
                                        action = "ignore"
                                        decision_reason = "ai:moderation_reply_block"
                                        moderation_state = "output_blocked"
                                        logger.info("ai_blocked_by_moderation message_id=%s", message.message_id)
                                    else:
                                        suggested_reply = ai_reply
                                        moderation_state = "output_ok"
                                        path_used = "rewrite"
                                else:
                                    suggested_reply = ai_reply
                                    path_used = "rewrite"
                            else:
                                suggested_reply = selected_seed.text
                                path_used = "seed"
                                downgrade_applied = True
                                decision_reason = "ai_generation_empty_fallback_to_seed"
            elif action == "auto_reply" and selected_seed is not None:
                suggested_reply = selected_seed.text
                path_used = "seed"

            if action == "auto_reply" and selected_seed is not None and settings.enable_seed_rotation_memory:
                seed_rotation_service.mark_used(
                    chat_id=message.chat_id,
                    category=policy.category,
                    seed_key=selected_seed.key,
                )
        except Exception:
            if decision_reason.startswith("ai_decision_skipped_due_to_budget"):
                logger.info("ai_decision_skipped_due_to_budget message_id=%s", message.message_id)
            else:
                action = "ignore"
                decision_reason = "ai_failure"
                logger.exception("AI decision/generation failed message_id=%s", message.message_id)

    logger.info(
        "Classified message_id=%s category=%s action=%s confidence=%s path=%s budget_state=%s moderation_state=%s",
        message.message_id,
        category,
        action,
        confidence,
        path_used if ai_path_used else "deterministic",
        budget_state,
        moderation_state,
    )

    throttle_blocked = False
    throttle_reason = "none"

    if action == "auto_reply" and settings.enable_low_risk_auto_reply:
        if category == "win_share":
            await safe_add_reaction(
                bot=context.bot,
                chat_id=message.chat_id,
                message_id=message.message_id,
                emoji="🔥",
                flow="win_share_intake",
            )
        elif category == "comeback_campaign":
            emoji = get_reaction(category)
            if emoji and reaction_cooldown.allow(
                chat_id=message.chat_id,
                category="comeback_campaign",
                cooldown_seconds=settings.comeback_reaction_cooldown_seconds,
            ):
                await safe_add_reaction(
                    bot=context.bot,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    emoji=emoji,
                    flow="comeback_campaign",
                )

        user_id = message.from_user.id if message.from_user else 0
        try:
            throttle_decision = auto_reply_throttle.evaluate_auto_reply_throttle(
                chat_id=message.chat_id,
                user_id=user_id,
                category=category,
                text=text,
                settings=settings,
            )
        except Exception:
            logger.exception(
                "Auto-reply throttle evaluation failed; allowing reply message_id=%s category=%s",
                message.message_id,
                category,
            )
            throttle_decision = None

        if throttle_decision and not throttle_decision.allowed:
            throttle_blocked = True
            throttle_reason = throttle_decision.reason
            action = "ignore"
            logger.info(
                "Auto reply blocked message_id=%s chat_id=%s user_id=%s reason=%s normalized_hash=%s",
                message.message_id,
                message.chat_id,
                user_id,
                throttle_decision.reason,
                throttle_decision.normalized_text_hash,
            )
        else:
            if throttle_decision:
                logger.info(
                    "Auto reply allowed message_id=%s chat_id=%s user_id=%s category=%s normalized_hash=%s",
                    message.message_id,
                    message.chat_id,
                    user_id,
                    category,
                    throttle_decision.normalized_text_hash,
                )
            if suggested_reply:
                reply_payload = suggested_reply
                allow_button = False
            else:
                _det_seeds = SEED_REPLIES.get(category, [])
                _det_seed = seed_rotation_service.pick_seed(
                    chat_id=message.chat_id,
                    category=category,
                    seeds=_det_seeds,
                    repeat_window_seconds=settings.ai_seed_repeat_window_seconds,
                    max_seed_reuse_per_window=settings.ai_max_seed_reuse_per_window,
                ) if _det_seeds else None
                if _det_seed:
                    base = RESPONSES.get(category, {})
                    if isinstance(base, dict) and base.get("button_text"):
                        reply_payload = {
                            "text": _det_seed.text,
                            "button_text": base.get("button_text"),
                            "button_url": base.get("button_url"),
                        }
                        allow_button = True
                    else:
                        reply_payload = _det_seed.text
                        allow_button = False
                    if settings.enable_seed_rotation_memory:
                        seed_rotation_service.mark_used(
                            chat_id=message.chat_id,
                            category=category,
                            seed_key=_det_seed.key,
                        )
                else:
                    reply_payload = generate_reply(category, text)
                    allow_button = True

            if category == "new_user":
                await safe_add_reaction(
                    bot=context.bot,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    emoji="🎉",
                    flow="new_user_onboarding",
                )

            reply_text, reply_markup = _prepare_reply_payload(
                reply_payload,
                allow_button=allow_button,
            )
            if reply_text:
                logger.info("Auto reply triggered for message_id=%s category=%s", message.message_id, category)
                kwargs = {}
                if settings.enable_threaded_replies:
                    kwargs["reply_to_message_id"] = message.message_id
                if reply_markup:
                    kwargs["reply_markup"] = reply_markup
                if category == "new_user":
                    kwargs["parse_mode"] = "HTML"
                await message.reply_text(reply_text, **kwargs)
                reply_sent = True
                if path_used == "seed":
                    logger.info("seed_reply_sent message_id=%s category=%s", message.message_id, category)
                if path_used == "rewrite":
                    logger.info("ai_rewritten_reply_sent message_id=%s category=%s", message.message_id, category)
                if path_used == "deterministic":
                    logger.info("deterministic_reply_sent message_id=%s category=%s", message.message_id, category)
    log_message(
        category,
        update,
        decision={
            "category": category,
            "action": action,
            "confidence": confidence,
            "reason": decision_reason,
            "path": path_used if ai_path_used else "deterministic",
            "category_before": category_before,
            "category_after": category,
            "ai_used": ai_path_used,
            "budget_state": budget_state,
            "moderation_state": moderation_state,
            "reply_sent": reply_sent,
            "downgrade_applied": downgrade_applied,
        },
        throttle_blocked=throttle_blocked,
        throttle_reason=throttle_reason,
    )

    if action == "suggest_only" and settings.enable_suggestions:
        suggestion_payload = suggested_reply or generate_reply(category, text)
        suggestion, _ = _prepare_reply_payload(suggestion_payload, allow_button=False)
        if suggestion and settings.admin_chat_id:
            logger.info("Suggestion forwarded for message_id=%s category=%s", message.message_id, category)
            admin_text = (
                f"Suggestion for message {message.message_id} in chat {message.chat_id}:\n"
                f"User: {message.from_user.username or message.from_user.id if message.from_user else 'unknown'}\n"
                f"Category: {category}\n"
                f"Original: {text}\n"
                f"Suggested reply: {suggestion}\n\n"
                f"Reply /approve, /reject, or /correct <category> to give feedback."
            )
            sent = await context.bot.send_message(chat_id=settings.admin_chat_id, text=admin_text)
            log_suggestion(
                bot_message_id=sent.message_id,
                original_message_id=message.message_id,
                chat_id=message.chat_id,
                original_text=text,
                suggested_reply=suggestion,
                category=category,
            )


async def _admin_feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, approved: bool) -> None:
    settings = get_settings()
    message = update.message
    if message is None:
        return
    if not settings.admin_chat_id or message.chat_id != settings.admin_chat_id:
        return
    replied_to = message.reply_to_message
    if replied_to is None:
        await message.reply_text("Reply to a suggestion message to give feedback.")
        return
    correct_category = context.args[0] if context.args else None
    found = log_feedback(
        bot_message_id=replied_to.message_id,
        approved=approved,
        correct_category=correct_category,
    )
    if found:
        label = "approved" if approved else "rejected"
        cat_note = f" (corrected to {correct_category})" if correct_category else ""
        await message.reply_text(f"Feedback recorded: {label}{cat_note}. The bot will learn from this.")
        logger.info("Feedback recorded bot_message_id=%s approved=%s correct_category=%s", replied_to.message_id, approved, correct_category)
    else:
        await message.reply_text("Could not find the suggestion. Make sure you reply to the bot's suggestion message.")


async def approve_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=True)


async def reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=False)


async def correct_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=True)


def setup_application():
    settings = get_settings()
    _get_ai_runtime(settings)
    application = ApplicationBuilder().token(settings.telegram_token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    application.add_handler(CommandHandler("approve", approve_handler))
    application.add_handler(CommandHandler("reject", reject_handler))
    application.add_handler(CommandHandler("correct", correct_handler))
    return application


async def start_bot(application) -> None:
    await application.initialize()
    await application.start()
    await application.updater.start_polling()


async def stop_bot(application) -> None:
    try:
        if application.updater:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram bot stopped")
    except Exception:
        logger.exception("Failed to stop Telegram bot cleanly")
