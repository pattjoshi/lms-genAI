import pytest

from app.config import Settings
from app.llm.budget import chat_cost_usd
from app.models import Role, User
from app.permissions import PERMISSIONS, PermissionDenied, Resource, Scope, scope_for
from app.scopes import student_list_query


def _user(role: Role, uid: int = 1) -> User:
    return User(id=uid, full_name="Test", email=f"{role}@x.in", role=role, city="Pune", is_active=True)


def test_every_role_has_every_resource():
    for role in Role:
        assert set(PERMISSIONS[role]) == set(Resource), role


def test_only_admin_sees_ai_usage():
    assert [r for r in Role if scope_for(r, Resource.AI_USAGE) != Scope.NONE] == [Role.admin]


@pytest.mark.parametrize("role", [Role.student, Role.support])
def test_student_and_support_cannot_list_students(role):
    with pytest.raises(PermissionDenied):
        student_list_query(_user(role))


def test_teacher_list_is_limited_to_own_courses():
    sql = str(student_list_query(_user(Role.teacher, uid=7)).compile(compile_kwargs={"literal_binds": True}))
    assert "courses.teacher_id = 7" in sql


def test_admin_list_has_no_scope_filter():
    sql = str(student_list_query(_user(Role.admin)).compile(compile_kwargs={"literal_binds": True}))
    assert "teacher_id" not in sql


def test_cost_formula():
    s = Settings(chat_price_input_per_1m=0.15, chat_price_output_per_1m=0.60)
    # 1,000 input + 500 output tokens = 0.00015 + 0.0003 USD
    assert chat_cost_usd(1000, 500, s) == pytest.approx(0.00045)


def test_placeholder_keys_count_as_missing():
    s = Settings(_env_file=None, openai_api_key="sk-...", langfuse_public_key="pk-lf-...", langfuse_secret_key="")
    assert s.openai_api_key is None
    assert not s.langfuse_enabled
