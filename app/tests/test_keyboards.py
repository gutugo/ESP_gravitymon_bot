from handlers.keyboards import (
    get_admin_keyboard,
    get_graph_keyboard,
    get_main_keyboard,
)


def test_main_keyboard_no_admin():
    kb = get_main_keyboard(is_admin=False)
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "⚙️ Админ" not in texts
    assert "📈 Графики" in texts


def test_main_keyboard_with_admin():
    kb = get_main_keyboard(is_admin=True)
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "⚙️ Админ" in texts


def test_graph_keyboard_periods():
    kb = get_graph_keyboard(period="day")
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    # Selected period has bullet marks
    assert "• 1 День •" in texts
    assert "1 Час" in texts  # not selected


def test_admin_keyboard_users():
    users = [
        {"chat_id": 1, "name": "Admin", "username": "admin"},
        {"chat_id": 2, "name": "User", "username": "user2"},
    ]
    kb = get_admin_keyboard(users, master_admin_id=1)
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("👑" in t for t in texts)
    assert any("❌" in t for t in texts)
    # Master admin row should NOT have ❌ button
    admin_row = kb.inline_keyboard[0]
    assert len(admin_row) == 1  # only info button, no remove
