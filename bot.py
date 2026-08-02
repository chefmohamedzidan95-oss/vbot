import logging
import json
import re
import os
import zipfile
from typing import Dict, List, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from providers import ProviderManager, BaseProvider, VideoResult

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CONFIG_PATH = "config.json"
PAGE_SIZE = 10


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_provider_manager(context: ContextTypes.DEFAULT_TYPE) -> ProviderManager:
    manager = context.application.bot_data.get("provider_manager")
    if manager is None:
        manager = ProviderManager(CONFIG_PATH)
        context.application.bot_data["provider_manager"] = manager
    return manager


def get_active_provider(context: ContextTypes.DEFAULT_TYPE) -> BaseProvider:
    manager = get_provider_manager(context)
    active_id = context.user_data.get("active_provider_id", "qfilm")
    provider = manager.get_provider(active_id)
    if not provider:
        provider = manager.get_provider("qfilm")
    return provider


# --- Keyboards ---

def _main_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    provider = get_active_provider(context)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 بحث عن فيلم أو مسلسل", callback_data="cmd_search")],
            [InlineKeyboardButton("📂 التصنيفات والأنواع", callback_data="cmd_categories")],
            [InlineKeyboardButton(f"🌐 المصدر: {provider.name}", callback_data="cmd_sources")],
            [InlineKeyboardButton("❓ مساعدة", callback_data="cmd_help")],
        ]
    )


def _back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 بحث جديد", callback_data="cmd_search")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home")],
        ]
    )


# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    provider = get_active_provider(context)
    welcome = (
        f"👋 مرحباً {user.first_name}!\n\n"
        "🍿 أهلاً بك في بوت <b>أفلام و مسلسلات FlixMix</b> 🎬\n\n"
        "✨ البوت يتيح لك البحث عن أفضل الأفلام والمسلسلات ومشاهدتها مباشرة داخل التليجرام عبر ميزة WebApp 📺\n\n"
        f"🌐 <b>المصدر الحالي:</b> {provider.name}\n\n"
        "📌 <b>طريقة الاستخدام:</b>\n"
        "• أرسل اسم الفيلم أو المسلسل للبحث مباشرة\n"
        "• أو اختر من قائمة <b>التصنيفات</b> لتصفح أنواع الأفلام والمسلسلات\n"
        "• اضغط زر <b>مشاهدة الآن</b> للمشاهدة المباشرة داخل مشغل البوت\n\n"
        "🔍 <b>ابدأ البحث الآن بإرسال النص أو اختر من القائمة أدناه:</b>"
    )
    await update.message.reply_text(welcome, reply_markup=_main_keyboard(context), parse_mode="HTML")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>دليل مستخدم بوت FlixMix 🍿</b>\n\n"
        "🔍 <b>كيفية البحث:</b>\n"
        "أرسل اسم الفيلم أو المسلسل باللغة العربية أو الإنجليزية.\n"
        "مثال: <code>spider</code> أو <code>شمس الأصيل</code> أو <code>باتمان</code>\n\n"
        "📂 <b>التصفح حسب التصنيف:</b>\n"
        "يمكنك الضغط على زر <b>التصنيفات</b> لتصفح الأفلام الأجنبية، العربية، الأكشن، المسلسلات، إلخ.\n\n"
        "🌐 <b>تغيير المصدر:</b>\n"
        "يمكنك التبديل بين المواقع والمصادر المتاحة عبر قسم <b>المصدر</b>.\n\n"
        "🍿 <b>المشاهدة عبر WebApp:</b>\n"
        "عند فتح تفاصيل المحتوى، اضغط على زر <b>🍿 مشاهدة الآن (Web App)</b> لتشغيل الفيديو فوراً داخل التليجرام بدون مغادرة البوت!\n\n"
        "📲 <b>الأوامر المتاحة:</b>\n"
        "/start - القائمة الرئيسية\n"
        "/help - دليل المساعدة\n"
        "/search - بحث جديد\n"
        "/files - تحميل ملفات مشروع البوت"
    )
    await update.message.reply_text(help_text, reply_markup=_main_keyboard(context), parse_mode="HTML")


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 أرسل اسم الفيلم أو المسلسل الذي تبحث عنه:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home")]]),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        return
    await _perform_search(update, context, query, page=1)


# --- Search & Results Logic ---

async def _perform_search(update_or_query, context: ContextTypes.DEFAULT_TYPE, query_str: str, page: int = 1):
    provider = get_active_provider(context)
    chat_id = update_or_query.effective_chat.id

    if hasattr(update_or_query, "message") and update_or_query.message:
        msg = await update_or_query.message.reply_text("⏳ جاري البحث...")
    else:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        msg = None

    try:
        results = provider.search(query_str, page=1)
    except Exception as e:
        logger.error(f"Search error: {e}")
        await _safe_edit_or_send(context, chat_id, "❌ حدث خطأ أثناء البحث. يرجى المحاولة مرة أخرى.", msg=msg)
        return

    if not results:
        await _safe_edit_or_send(
            context,
            chat_id,
            f"❌ لم يتم العثور على نتائج للبحث عن: <b>{query_str}</b>\nجرّب بكلمة مفتاحية أخرى.",
            reply_markup=_back_home_keyboard(),
            msg=msg,
        )
        return

    context.user_data["search_results"] = [
        {
            "vid": r.vid,
            "title": r.title,
            "thumb_url": r.thumb_url,
            "duration": r.duration,
            "labels": r.labels,
            "watch_url": r.watch_url,
            "provider_id": r.provider_id,
        }
        for r in results
    ]
    context.user_data["current_query"] = query_str
    context.user_data["search_type"] = "search"

    await _send_results_page(context, chat_id, page=page, edit_message=msg)


async def _send_results_page(context: ContextTypes.DEFAULT_TYPE, chat_id: int, page: int = 1, edit_message=None):
    results = context.user_data.get("search_results", [])
    query_str = context.user_data.get("current_query", "")
    search_type = context.user_data.get("search_type", "search")

    total_items = len(results)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)

    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start_idx = (page - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_items)
    page_items = results[start_idx:end_idx]

    if search_type == "category":
        header_text = f"🍿 <b>أفلام و مسلسلات FlixMix</b>\n📂 <b>تصفح الفئة: {query_str}</b>\n📄 (صفحة {page} من {total_pages})\n\nاختر المحتوى الذي تريد مشاهدته:"
    else:
        header_text = f"🍿 <b>أفلام و مسلسلات FlixMix</b>\n🔎 <b>نتائج البحث عن:</b> <code>{query_str}</code>\n📄 (صفحة {page} من {total_pages} | إجمالي {total_items} نتيجة)\n\nاختر من القائمة أدناه:"

    buttons = []
    for idx, item in enumerate(page_items, start=start_idx):
        title = item["title"]
        label = f"🎬 {title[:48]}..." if len(title) > 48 else f"🎬 {title}"
        if "مسلسل" in item.get("labels", []) or "مسلسل" in title:
            label = f"📺 {title[:48]}..." if len(title) > 48 else f"📺 {title}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"v_{idx}")])

    # Pagination navigation row
    nav_row = []
    if page > 1:
        prev_cb = f"sp_{page-1}" if search_type == "search" else f"cp_{context.user_data.get('current_cat_id', '')}_{page-1}"
        nav_row.append(InlineKeyboardButton("◀️ السابقة", callback_data=prev_cb))
    
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="cmd_ignore"))

    if page < total_pages:
        next_cb = f"sp_{page+1}" if search_type == "search" else f"cp_{context.user_data.get('current_cat_id', '')}_{page+1}"
        nav_row.append(InlineKeyboardButton("التالية ▶️", callback_data=next_cb))

    buttons.append(nav_row)
    buttons.append([
        InlineKeyboardButton("🔍 بحث جديد", callback_data="cmd_search"),
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home"),
    ])

    reply_markup = InlineKeyboardMarkup(buttons)

    if edit_message:
        try:
            await edit_message.edit_text(header_text, reply_markup=reply_markup, parse_mode="HTML")
            return
        except Exception:
            pass

    await context.bot.send_message(chat_id=chat_id, text=header_text, reply_markup=reply_markup, parse_mode="HTML")


# --- Video Details & Playback ---

async def _handle_video_select(query, context: ContextTypes.DEFAULT_TYPE, index: int):
    results = context.user_data.get("search_results", [])
    if not results or index >= len(results):
        await query.message.reply_text("❌ حدث خطأ، يرجى إعادة البحث.")
        return

    r_data = results[index]
    provider = get_active_provider(context)

    await context.bot.send_chat_action(query.message.chat_id, ChatAction.TYPING)

    try:
        details = provider.get_video_details(r_data["vid"], extra=r_data)
    except Exception as e:
        logger.error(f"Details error: {e}")
        await query.message.reply_text("❌ حدث خطأ أثناء تحميل التفاصيل.", reply_markup=_back_home_keyboard())
        return

    # Generate WebApp Watch URL
    web_app_url = provider.get_web_app_url(details)

    context.user_data["selected_video_details"] = {
        "vid": details.vid,
        "title": details.title,
        "description": details.description,
        "categories": details.categories,
        "duration": details.duration,
        "views": details.views,
        "quality": details.quality,
        "thumb_url": details.thumb_url,
        "is_series": details.is_series,
        "watch_url": details.watch_url,
        "web_app_url": web_app_url,
    }

    await _send_video_card(query, context, details, web_app_url)


async def _send_video_card(query, context, details: VideoResult, web_app_url: str):
    title = details.title or "غير معروف"
    desc = details.description or "لا يوجد وصف متاح."
    if len(desc) > 400:
        desc = desc[:397] + "..."
    cats = " | ".join(details.categories) if details.categories else "غير مصنف"
    dur = f"⏱️ <b>المدة:</b> {details.duration}\n" if details.duration else ""
    views = f"👁️ <b>المشاهدات:</b> {details.views:,}\n" if details.views else ""
    quality = f"📺 <b>الجودة:</b> {details.quality}\n" if details.quality else ""
    series_tag = "📺 <b>مسلسل</b>" if details.is_series else "🎬 <b>فيلم</b>"

    # NOTE: Clean UI with NO raw website links in text (as requested!)
    caption = (
        f"{series_tag}\n"
        f"🍿 <b>{title}</b>\n\n"
        f"📂 <b>التصنيف:</b> {cats}\n"
        f"{dur}"
        f"{views}"
        f"{quality}\n"
        f"📝 <b>القصة والتفاصيل:</b>\n{desc}\n\n"
        f"👇 <b>اضغط على زر المشاهدة أدناه لتشغيل الفيديو داخل البوت (Web App):</b>"
    )

    buttons = [
        [InlineKeyboardButton("🍿 مشاهدة الآن (Web App)", web_app=WebAppInfo(url=web_app_url))],
    ]

    if details.is_series:
        buttons.append([InlineKeyboardButton("🎬 عرض الحلقات", callback_data=f"episodes_{details.vid}")])

    buttons.append([
        InlineKeyboardButton("⬅️ رجوع للنتائج", callback_data="cmd_back_results"),
        InlineKeyboardButton("🏠 الرئيسية", callback_data="cmd_home"),
    ])

    reply_markup = InlineKeyboardMarkup(buttons)
    thumb = details.thumb_url or context.user_data.get("selected_video", {}).get("thumb_url", "")

    try:
        if thumb and thumb.startswith("http"):
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumb,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except Exception:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


# --- Episodes Handler ---

async def _handle_episodes(query, context: ContextTypes.DEFAULT_TYPE, vid: str, page: int = 1):
    details_dict = context.user_data.get("selected_video_details", {})
    provider = get_active_provider(context)

    await context.bot.send_chat_action(query.message.chat_id, ChatAction.TYPING)

    watch_url = details_dict.get("watch_url", "")
    episodes = provider.get_series_episodes(watch_url or vid)

    if not episodes:
        await query.message.reply_text("❌ لم يتم العثور على حلقات لهذا المسلسل.")
        return

    context.user_data["episodes_list"] = [
        {
            "vid": e.vid,
            "title": e.title,
            "watch_url": e.watch_url,
        }
        for e in episodes
    ]

    total_ep = len(episodes)
    total_pages = max(1, (total_ep + PAGE_SIZE - 1) // PAGE_SIZE)
    
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_ep)
    page_eps = episodes[start_idx:end_idx]

    series_title = details_dict.get("title", "")
    text = f"📺 <b>حلقات: {series_title}</b>\n📄 (صفحة {page} من {total_pages} | إجمالي {total_ep} حلقة)\n\nاختر الحلقة:"

    buttons = []
    for idx, ep in enumerate(page_eps, start=start_idx):
        buttons.append([InlineKeyboardButton(f"▶️ {ep.title}", callback_data=f"ep_{idx}")])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ السابقة", callback_data=f"epp_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="cmd_ignore"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("التالية ▶️", callback_data=f"epp_{page+1}"))

    buttons.append(nav_row)
    buttons.append([
        InlineKeyboardButton("⬅️ رجوع للمسلسل", callback_data="cmd_back_results"),
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home"),
    ])

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _handle_episode_select(query, context: ContextTypes.DEFAULT_TYPE, index: int):
    episodes = context.user_data.get("episodes_list", [])
    if not episodes or index >= len(episodes):
        await query.message.reply_text("❌ حدث خطأ، يرجى اختيار الحلقة مجدداً.")
        return

    ep = episodes[index]
    provider = get_active_provider(context)

    await context.bot.send_chat_action(query.message.chat_id, ChatAction.TYPING)
    details = provider.get_video_details(ep["vid"], extra=ep)
    web_app_url = provider.get_web_app_url(details)

    await _send_video_card(query, context, details, web_app_url)


# --- Categories & Sources Handlers ---

async def _handle_categories_menu(query_or_update, context: ContextTypes.DEFAULT_TYPE):
    provider = get_active_provider(context)
    cats = provider.get_categories()

    text = f"📂 <b>تصنيفات وقوائم المصدر: {provider.name}</b>\n\nاختر التصنيف لعرض المحتوى:"
    
    buttons = []
    # Display categories in 2 columns
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(f"{cats[i].icon} {cats[i].name}", callback_data=f"cat_{cats[i].id}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(f"{cats[i+1].icon} {cats[i+1].name}", callback_data=f"cat_{cats[i+1].id}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home")])
    reply_markup = InlineKeyboardMarkup(buttons)

    chat_id = query_or_update.effective_chat.id
    if hasattr(query_or_update, "message") and query_or_update.message:
        await query_or_update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")


async def _handle_category_select(query, context: ContextTypes.DEFAULT_TYPE, cat_id: str, page: int = 1):
    provider = get_active_provider(context)
    cat_obj = next((c for c in provider.get_categories() if c.id == cat_id), None)
    cat_name = cat_obj.name if cat_obj else cat_id

    await context.bot.send_chat_action(query.message.chat_id, ChatAction.TYPING)

    results = provider.get_by_category(cat_id, page=1)
    if not results:
        await query.message.reply_text("❌ لا توجد نتائج متاح في هذا التصنيف حالياً.")
        return

    context.user_data["search_results"] = [
        {
            "vid": r.vid,
            "title": r.title,
            "thumb_url": r.thumb_url,
            "duration": r.duration,
            "labels": r.labels,
            "watch_url": r.watch_url,
            "provider_id": r.provider_id,
        }
        for r in results
    ]
    context.user_data["current_query"] = cat_name
    context.user_data["current_cat_id"] = cat_id
    context.user_data["search_type"] = "category"

    await _send_results_page(context, query.message.chat_id, page=page, edit_message=query.message)


async def _handle_sources_menu(query, context: ContextTypes.DEFAULT_TYPE):
    manager = get_provider_manager(context)
    active_provider = get_active_provider(context)
    providers_list = manager.list_providers()

    text = (
        "🌐 <b>إدارة مواقع ومصادر الأفلام والمسلسلات</b>\n\n"
        "يمكنك التبديل بين المصادر المتاحة لجلب نتائج أكثر:\n\n"
        f"✅ <b>المصدر الحالي:</b> {active_provider.name}\n"
        f"📝 <i>{active_provider.description}</i>\n"
    )

    buttons = []
    for p in providers_list:
        is_active = (p.id == active_provider.id)
        btn_text = f"✅ {p.name}" if is_active else f"🌐 {p.name}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"src_{p.id}")])

    buttons.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def _handle_source_switch(query, context: ContextTypes.DEFAULT_TYPE, provider_id: str):
    manager = get_provider_manager(context)
    provider = manager.get_provider(provider_id)

    if provider:
        context.user_data["active_provider_id"] = provider.id
        await query.answer(f"تم التبديل إلى: {provider.name}", show_alert=True)
        await query.message.reply_text(
            f"✅ <b>تم تغيير المصدر بنجاح إلى:</b> {provider.name}\n\nيمكنك الآن البحث أو تصفح التصنيفات التابعة لهذا المصدر.",
            reply_markup=_main_keyboard(context),
            parse_mode="HTML",
        )
    else:
        await query.answer("❌ المصدر غير متاح", show_alert=True)


# --- Main Callback Router ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cmd_ignore":
        return

    if data == "cmd_home":
        await query.message.reply_text("🏠 <b>القائمة الرئيسية</b>", reply_markup=_main_keyboard(context), parse_mode="HTML")
        return

    if data == "cmd_search":
        await query.message.reply_text(
            "🔍 أرسل اسم الفيلم أو المسلسل الذي تبحث عنه:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cmd_home")]]),
        )
        return

    if data == "cmd_categories":
        await _handle_categories_menu(query, context)
        return

    if data == "cmd_sources":
        await _handle_sources_menu(query, context)
        return

    if data == "cmd_help":
        await help_cmd(update, context)
        return

    if data == "cmd_back_results":
        if "search_results" in context.user_data:
            await _send_results_page(context, query.message.chat_id, page=1)
        else:
            await query.message.reply_text("🏠 القائمة الرئيسية", reply_markup=_main_keyboard(context))
        return

    # Prefix Routing
    if data.startswith("sp_"):
        page = int(data.split("_")[1])
        await _send_results_page(context, query.message.chat_id, page=page, edit_message=query.message)
        return

    if data.startswith("cp_"):
        parts = data.split("_")
        cat_id = parts[1]
        page = int(parts[2])
        await _send_results_page(context, query.message.chat_id, page=page, edit_message=query.message)
        return

    if data.startswith("v_"):
        index = int(data.split("_")[1])
        await _handle_video_select(query, context, index)
        return

    if data.startswith("cat_"):
        cat_id = data.replace("cat_", "", 1)
        await _handle_category_select(query, context, cat_id, page=1)
        return

    if data.startswith("src_"):
        provider_id = data.replace("src_", "", 1)
        await _handle_source_switch(query, context, provider_id)
        return

    if data.startswith("episodes_"):
        vid = data.replace("episodes_", "", 1)
        await _handle_episodes(query, context, vid, page=1)
        return

    if data.startswith("ep_"):
        index = int(data.split("_")[1])
        await _handle_episode_select(query, context, index)
        return

    if data.startswith("epp_"):
        page = int(data.split("_")[1])
        vid = context.user_data.get("selected_video_details", {}).get("vid", "")
        await _handle_episodes(query, context, vid, page=page)
        return


# --- Utility Helpers & Commands ---

async def _safe_edit_or_send(context, chat_id, text, reply_markup=None, msg=None, parse_mode="HTML"):
    if msg:
        try:
            await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)


async def files_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zip and send all project files to the user."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = "/tmp/FlixMix_telegram_bot_files.zip"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(project_dir):
                if "__pycache__" in root or ".git" in root:
                    continue
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, project_dir)
                    zf.write(filepath, arcname)

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(zip_path, "rb"),
            caption="📁 <b>ملفات مشروع بوت FlixMix 🍿</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Files command error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء إرسال الملفات.", reply_markup=_main_keyboard(context))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception in handler:", exc_info=context.error)


def main():
    config = load_config()
    token = config.get("telegram_token", "")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.error("Telegram bot token not set in config.json")
        print("❌ يرجى إضافة توكن البوت في ملف config.json")
        return

    app = Application.builder().token(token).build()
    app.bot_data["provider_manager"] = ProviderManager(CONFIG_PATH)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("files", files_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    logger.info("FlixMix Bot started")
    print("✅ تم تشغيل بوت FlixMix بنجاح! أرسل /start في تليجرام")
    app.run_polling()


if __name__ == "__main__":
    main()
