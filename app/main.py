from fastapi import FastAPI, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import os, re

from .db import SessionLocal, engine
from .models import Base, Inventory

app = FastAPI()
MM_TOKEN = os.getenv("MM_TOKEN", "")

# user잘못 커밋해서 다시 보냄...

# DB 테이블 보장(이미 init.sql로 생성되지만, idempotent 보완용)
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 카테고리 한국어 ↔ 내부코드 매핑
CATEGORY_ALIASES = {
    "우산": "umbrella",
    "우산들": "umbrella",
    "umbrella": "umbrella",
    "c타입": "charger_c",
    "c타입충전기": "charger_c",
    "c타입 충전기": "charger_c",
    "충전기": "charger_c",  # 원하면 더 세분화 가능
    "ctype": "charger_c",
}

def normalize_category(raw: str) -> Optional[str]:
    key = raw.strip().lower().replace(" ", "")
    # 원문 보존 매칭
    if raw in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw]
    # 소문자 스페이스 제거 버전도 검사
    for k, v in CATEGORY_ALIASES.items():
        if key == k.replace(" ", "").lower():
            return v
    return None

def mm_text_response(text: str, in_channel: bool = False) -> JSONResponse:
    # Mattermost JSON 응답 형식
    return JSONResponse({
        "response_type": "in_channel" if in_channel else "ephemeral",
        "text": text
    })

@app.post("/mm/command")
async def mm_command(
    token: str = Form(...),
    user_name: str = Form(...),      # 실행한 사용자 이름
    user_id: str = Form(...),        # 실행한 사용자 ID
    text: str = Form(""),            # 사용자가 슬래시 명령어 뒤에 친 내용
    team_domain: str = Form(None),
    channel_name: str = Form(None),
    command: str = Form(None),
    db: Session = Depends(get_db)
):
    # 토큰 검증
    if token != MM_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 파싱: "현황" / "대여 우산" / "반납 우산" / "전달 우산 @상대"
    raw = text.strip()

    # 1) 현황
    if raw in ("현황", "상태", "status"):
        return status_view(db)

    # 2) 대여 <카테고리> [닉네임]
    m = re.match(r"^(대여|빌려|rent)\s+(\S+)(?:\s+(.+))?$", raw, re.IGNORECASE)
    if m:
        cat_raw = m.group(2).strip()
        nickname = m.group(3).strip() if m.group(3) else user_name  # 닉네임 없으면 user_name fallback
        category = normalize_category(cat_raw)
        if not category:
            return mm_text_response(f"알 수 없는 물품 종류입니다: {cat_raw}")
        return rent_item(db, requester=nickname, category=category)

    # 3) 반납 <카테고리> [닉네임]
    m = re.match(r"^(반납|return)\s+(\S+)(?:\s+(.+))?$", raw, re.IGNORECASE)
    if m:
        cat_raw = m.group(2).strip()
        nickname = m.group(3).strip() if m.group(3) else user_name
        category = normalize_category(cat_raw)
        if not category:
            return mm_text_response(f"알 수 없는 물품 종류입니다: {cat_raw}")
        return return_item(db, requester=nickname, category=category)

    # 4) 전달 <카테고리> <보내는사람닉> <받는사람닉>
    m = re.match(r"^(전달|transfer)\s+(\S+)\s+(\S+)\s+(\S+)$", raw, re.IGNORECASE)
    if m:
        cat_raw = m.group(2).strip()
        from_user = m.group(3).strip()
        to_user = m.group(4).strip()
        category = normalize_category(cat_raw)
        if not category:
            return mm_text_response(f"알 수 없는 물품 종류입니다: {cat_raw}")
        return transfer_item(db, from_user=from_user, to_user=to_user, category=category)


    # 도움말
    help_text = (
        "사용법 예시:\n"
        "- `/대여 현황` : 현재 대여 현황 보기\n"
        "- `/대여 대여 우산 (이름)` : 남는 우산을 본인 이름으로 대여\n"
        "- `/대여 반납 우산 (이름)` : 본인이 대여한 우산 반납\n"
        "- `/대여 전달 우산 (내 이름) (전달한 사람 이름)` : 본인 우산을 해당 사용자에게 양도\n"
        "\n*규칙: 한 사람이 같은 종류(카테고리)에서는 1개만 대여 가능*\n"
    )
    return mm_text_response(help_text)

def status_view(db: Session) -> JSONResponse:
    rows = db.query(Inventory).order_by(Inventory.category, Inventory.name).all()

    # 카테고리별 표
    lines = ["**대여 현황**"]
    if not rows:
        lines.append("_아직 등록된 물품이 없습니다_")
        return mm_text_response("\n".join(lines), in_channel=True)

    # 카테고리 -> [ (name, holder or '') ]
    by_cat: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append((r.name, r.holder or ""))

    for cat, items in by_cat.items():
        pretty_cat = "우산" if cat == "umbrella" else ("C타입 충전기" if cat == "charger_c" else cat)
        lines.append(f"\n- **{pretty_cat}**")
        for name, holder in items:
            holder_view = holder if holder else "_(대여 가능)_"
            lines.append(f"  - {name} → {holder_view}")
    return mm_text_response("\n".join(lines), in_channel=True)

def rent_item(db: Session, requester: str, category: str) -> JSONResponse:
    # 동일 카테고리 중복 대여 금지
    already = db.query(Inventory).filter(Inventory.category == category, Inventory.holder == requester).first()
    if already:
        pretty_cat = to_pretty(category)
        return mm_text_response(f"{requester}님은 이미 {pretty_cat} 카테고리에서 '{already.name}'을(를) 대여 중입니다.")

    # 남은 아이템 하나 배정
    free_item = db.query(Inventory).filter(Inventory.category == category, Inventory.holder.is_(None)).first()
    if not free_item:
        pretty_cat = to_pretty(category)
        return mm_text_response(f"{pretty_cat} 카테고리에 현재 대여 가능한 아이템이 없습니다.")

    free_item.holder = requester
    db.commit()
    db.refresh(free_item)
    return mm_text_response(f"대여 완료: {free_item.name} → {requester}", in_channel=True)

def return_item(db: Session, requester: str, category: str) -> JSONResponse:
    item = db.query(Inventory).filter(Inventory.category == category, Inventory.holder == requester).first()
    if not item:
        pretty_cat = to_pretty(category)
        return mm_text_response(f"{requester}님은 {pretty_cat} 카테고리에 대여 중인 물품이 없습니다.")
    item.holder = None
    db.commit()
    return mm_text_response(f"반납 완료: {item.name} ← {requester}", in_channel=True)

def transfer_item(db: Session, from_user: str, to_user: str, category: str) -> JSONResponse:
    # from_user가 해당 카테고리 보유 중이어야 함
    item = db.query(Inventory).filter(Inventory.category == category, Inventory.holder == from_user).first()
    if not item:
        pretty_cat = to_pretty(category)
        return mm_text_response(f"{from_user}님은 {pretty_cat} 카테고리에 대여 중인 물품이 없습니다.")

    # to_user가 같은 카테고리 이미 보유 중이면 불가
    conflict = db.query(Inventory).filter(Inventory.category == category, Inventory.holder == to_user).first()
    if conflict:
        pretty_cat = to_pretty(category)
        return mm_text_response(f"{to_user}님은 이미 {pretty_cat} 카테고리에서 '{conflict.name}'을(를) 보유 중이어서 전달할 수 없습니다.")

    # 전달: 반납 후 즉시 재대여 처리
    item.holder = to_user
    db.commit()
    return mm_text_response(f"전달 완료: {item.name} → {to_user} (from {from_user})", in_channel=True)

def to_pretty(category: str) -> str:
    if category == "umbrella":
        return "우산"
    if category == "charger_c":
        return "C타입 충전기"
    return category
