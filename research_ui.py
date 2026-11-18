"""Poster reading, spoken preparation goals, real bibliographic results."""
import base64
import hashlib
import html
import io
import json
import warnings
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st

from camera_component import live_camera
from poster_demo import show_poster_demo

FIELDS = ["자료명", "핵심 내용", "필요한 지식", "준비 방향", "확인할 사항"]
ASSETS = Path(__file__).with_name("assets")


def card_heading(number, title, caption):
    st.markdown(f'<div class="prism-card-heading"><span class="card-step">{html.escape(number)}</span>'
                f'<div><h4>{html.escape(title)}</h4><p>{html.escape(caption)}</p></div></div>', unsafe_allow_html=True)


def empty_preview():
    st.markdown('''<div class="prism-photo-empty prism-live-preview">
<div class="preview-scene" aria-hidden="true"><span class="preview-sticker sticker-photo">▧</span>
<div class="friend preview-friend friend-book"><em class="book-pages"></em><em class="book-spine"></em><div class="friend-eyes"><i></i><i></i></div><b></b></div>
<span class="preview-sticker sticker-book">≡</span><span class="preview-spark spark-a">✦</span><span class="preview-spark spark-b">✧</span></div>
<h4>어떤 도전을 준비해 볼까요?</h4>
<p>사진 속 단서를 읽고<br>나에게 필요한 책과 논문으로 연결해요.</p>
<div class="preview-trail" aria-hidden="true"><span>사진</span><i>→</i><span>준비</span><i>→</i><span>발견</span></div>
<small>예시 화면 보기로 먼저 둘러보세요</small></div>''', unsafe_allow_html=True)


def prepare_image(raw, max_side=1600):
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError("사진은 12MB 이하로 올려 주세요.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > 24_000_000:
                    raise ValueError("사진 해상도가 너무 큽니다. 사진 앱에서 크기를 줄인 뒤 올려 주세요.")
                image = ImageOps.exif_transpose(source)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
                else:
                    image = image.convert("RGB")
                image.thumbnail((max_side, max_side))
                output = io.BytesIO()
                image.save(output, "JPEG", quality=85)
                cooked = output.getvalue()
    except ValueError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("읽을 수 있는 PNG·JPEG·WebP 사진으로 다시 올려 주세요.") from None
    if len(cooked) > 2_000_000:
        raise ValueError("변환한 사진도 큽니다. 필요한 부분만 잘라 올리거나 1024px로 줄여 주세요.")
    return cooked, image.size


def fingerprint(raw, goal):
    return hashlib.sha256(raw + goal.strip().encode()).hexdigest()


def validate_reading(data):
    if not isinstance(data.get("result"), dict) or set(data["result"]) != set(FIELDS):
        raise ValueError("분석 결과의 다섯 항목을 확인하지 못했습니다.")
    if not all(isinstance(v, str) for v in data["result"].values()):
        raise ValueError("분석 결과 형식이 올바르지 않습니다.")
    for key in ["visible_facts", "preparation", "search_topics"]:
        if not isinstance(data.get(key), list):
            raise ValueError("분석 결과 목록 형식이 올바르지 않습니다.")
    return data


def resource_cards(data, prefix="resources"):
    if not data:
        return
    st.caption("실제 서지 검색 결과입니다. 검색어 관련성 순으로 표시하며, 책·논문 전체 내용을 AI가 읽었다는 뜻은 아닙니다.")
    for warning in data.get("warnings", []):
        st.info(str(warning))
    book_tab, paper_tab = st.tabs(["도서", "논문"])
    for tab, key in [(book_tab, "books"), (paper_tab, "papers")]:
        with tab:
            items = data.get(key, [])
            if not items:
                st.info("검색 결과가 없어요. 더 짧은 키워드나 영어 검색어로 바꿔 보세요.")
            for index, item in enumerate(items[:6]):
                with st.container(border=True):
                    cover, text = st.columns([1, 5]) if key == "books" and item.get("cover") else (None, st.container())
                    if cover:
                        cover.image(item["cover"], width=85)
                    with text:
                        st.text(item.get("title", "제목 확인 불가"))
                        st.caption(" · ".join(filter(None, [", ".join(item.get("authors", [])),
                            str(item.get("year") or "연도 확인 불가"), item.get("source", "")])))
                        if item.get("journal"):
                            st.caption(item["journal"])
                        url = item.get("url", "")
                        if url.startswith(("https://openlibrary.org/works/OL", "https://doi.org/10.")):
                            st.link_button("출처에서 확인 ↗", url, key=f"{prefix}-{key}-{index}")
    links = data.get("external_links", {})
    for label, url in links.items():
        if url.startswith(("https://search.kyobobook.co.kr/search?", "https://arxiv.org/search/?")):
            st.link_button(str(label) + " ↗", url, key=f"{prefix}-external-{label}")
    st.caption("Open Library는 한국어 도서가 적을 수 있어요. 국내 도서는 교보문고 검색으로 이어갈 수 있습니다. 외부 검색 버튼은 해당 사이트의 검색 화면을 엽니다.")


def run_analysis(raw, goal, url, code, api, nonce=None):
    cooked, size = prepare_image(raw)
    request_id = fingerprint(cooked, goal)
    previous = st.session_state.get("poster_reading")
    if previous and previous["request_id"] == request_id:
        if nonce:
            st.session_state["camera_ack"] = nonce
        return
    try:
        with st.spinner("포스터에서 읽은 사실과 준비에 필요한 지식을 나누고 있어요…"):
            data = validate_reading(api(url, code, "/analyze", {
                "image_b64": base64.b64encode(cooked).decode(), "mime_type": "image/jpeg", "goal": goal}))
        search = None
        topics = data.get("search_topics", [])
        if data.get("supported") and topics:
            query = str(topics[0].get("english") or topics[0].get("korean") or "").strip()[:160]
            if len(query) >= 2:
                with st.spinner("실제 도서와 논문을 찾고 있어요…"):
                    try:
                        search = api(url, code, "/resources", {"query": query, "kind": "all"})
                    except ValueError as error:
                        st.info(str(error))
                st.session_state["resource_query"] = query
                st.session_state["poster_resources"] = search
        st.session_state["poster_reading"] = {"data": data, "request_id": request_id,
            "preview": cooked, "goal": goal, "resources": search, "size": list(size)}
    finally:
        if nonce:
            st.session_state["camera_ack"] = nonce


def preparation_goal(url, code, error, api):
    with st.expander("음성으로 내 준비 조건 말하기"):
        st.caption("내 수준·관심 분야·준비 기간을 1분 이내로 말해 주세요. 녹음은 버튼을 눌렀을 때만 서버와 Gemini로 전송됩니다.")
        voice_source = st.radio("음성 입력 방식", ["직접 녹음", "WAV 파일 업로드"], horizontal=True, key="voice_source")
        if voice_source == "직접 녹음":
            recorded = st.audio_input("예: 파이썬 입문자이고 AI 공모전 준비 기간은 2주예요", sample_rate=16000, key="prep_voice")
        else:
            recorded = st.file_uploader("1분 이내의 내 준비 조건 녹음", type=["wav"], max_upload_size=2, key="prep_voice_file")
        if st.button("녹음한 조건 반영", disabled=recorded is None or bool(error), key="apply_prep_voice"):
            raw = recorded.getvalue()
            if len(raw) > 2_000_000:
                st.error("녹음은 1분 이내로 해 주세요.")
            else:
                try:
                    with st.spinner("말한 준비 조건을 정리하고 있어요…"):
                        voice = api(url, code, "/listen", {"audio_b64": base64.b64encode(raw).decode(), "mime_type": "audio/wav"})
                    st.session_state["prep_goal"] = str(voice.get("goal", ""))[:1000]
                    st.session_state["prep_transcript"] = voice
                except ValueError as exc:
                    st.error(str(exc))
        if st.session_state.get("prep_transcript"):
            voice = st.session_state["prep_transcript"]
            st.text(voice.get("transcript", ""))
            if voice.get("unclear"):
                st.info("잘 들리지 않은 부분이 있어요. 아래 준비 조건을 확인하고 수정해 주세요.")
            st.caption(f"녹음 {voice.get('duration', '?')}초 · 사용 토큰 {voice.get('tokens') or '확인 불가'}")
    return st.text_area("내 수준과 준비 조건", placeholder="예: 파이썬 기초를 배웠고, 접근성 AI 공모전을 2주 동안 준비하고 싶어요.",
                        max_chars=1000, key="prep_goal", height=95)


def poster_workspace(url, code, error, api):
    st.subheader("포스터 한 장에서, 다음에 읽을 자료까지")
    st.caption("공모전·대외활동·학회 포스터를 읽고 준비에 도움이 되는 실제 도서와 논문을 찾습니다.")
    input_col, preview_col = st.columns([1.12, 1], gap="large")
    preview_box = preview_col.container(border=True, key="prism_preview_card")
    with preview_box:
        card_heading("03", "사진 미리보기", "분석할 자료를 먼저 확인해요")
    with input_col:
        with st.container(border=True, key="prism_prep_card"):
            card_heading("01", "나의 준비 이야기 · 선택", "건너뛰어도 괜찮아요. 수준과 기간을 알려주면 더 반영해요")
            goal = preparation_goal(url, code, error, api)
        with st.container(border=True, key="prism_source_card"):
            card_heading("02", "도전의 단서 넣기", "사진·카메라 중 편한 방식을 골라요")
            if st.button("예시 화면 보기 · AI 요청 없음", key="poster_demo_open"):
                show_poster_demo()
            mode = st.radio("자료 입력", ["사진 업로드", "실시간 카메라", "간편 촬영"], horizontal=True, key="poster_input")
            raw, nonce, automatic = None, None, False
            if st.session_state.get("camera_input_error"):
                st.error(st.session_state.pop("camera_input_error"))
            if mode == "실시간 카메라":
                st.caption("미리보기는 기기에서만 재생됩니다. 자동 분석은 분석이 끝난 뒤 15초 간격으로 최대 3회 전송하고, 비슷한 화면은 건너뜁니다.")
                captured = live_camera(not bool(error), st.session_state.get("camera_ack"))
                if captured and isinstance(captured, dict) and captured.get("id") != st.session_state.get("camera_seen"):
                    st.session_state["camera_seen"] = captured.get("id")
                    nonce = captured.get("id")
                    try:
                        raw = base64.b64decode(captured.get("image_b64", ""), validate=True)
                        automatic = True
                        st.session_state["last_camera_photo"] = raw
                    except (ValueError, TypeError):
                        st.session_state["camera_input_error"] = "촬영한 화면을 읽지 못했습니다. 다시 촬영해 주세요."
                else:
                    raw = st.session_state.get("last_camera_photo")
            elif mode == "간편 촬영":
                if st.toggle("촬영용 카메라 켜기", key="simple_camera_on"):
                    photo = st.camera_input("포스터를 화면에 맞춰 찍어 주세요", key="simple_poster_camera")
                    raw = photo.getvalue() if photo else None
            else:
                uploaded = st.file_uploader("포스터·논문 도표 사진", type=["png", "jpg", "jpeg", "webp"],
                                            max_upload_size=12, key="poster_upload")
                raw = uploaded.getvalue() if uploaded else None
            if mode != "실시간 카메라":
                sample = ASSETS / "example_poster.png"
                if sample.exists() and st.button("가상 공모전 포스터 불러오기", key="load_poster_sample"):
                    st.session_state["sample_poster_active"] = True
                if raw:
                    st.session_state["sample_poster_active"] = False
                elif st.session_state.get("sample_poster_active") and sample.exists():
                    raw = sample.read_bytes()
                    st.caption("기능 시험용 가상 포스터입니다. 실제 모집 공고가 아닙니다.")
    ready = False
    if raw:
        try:
            cooked, size = prepare_image(raw)
            with preview_box:
                st.image(cooked, caption="분석할 사진", width=340)
                st.caption(f"전송용 {size[0]}×{size[1]}px · {len(cooked):,}B · base64 {4*((len(cooked)+2)//3):,}자")
            ready = True
        except ValueError as exc:
            st.error(str(exc))
    if not raw:
        with preview_box:
            empty_preview()
    st.caption("분석 시 선택한 이미지와 준비 조건이 PRISM 서버와 Gemini로 전송됩니다. 얼굴·연락처·신분증이 보이는 부분은 가려 주세요.")
    clicked = st.button("포스터 읽고 자료 찾기 ↗", type="primary", disabled=not ready or bool(error), key="read_poster")
    if nonce and (not ready or error):
        st.session_state["camera_ack"] = nonce
        st.session_state["camera_input_error"] = "촬영한 화면을 처리하지 못했습니다. 사진 크기와 앱 연결 상태를 확인해 주세요."
        st.rerun()
    if (clicked or automatic) and ready and not error:
        try:
            run_analysis(raw, goal, url, code, api, nonce)
        except ValueError as exc:
            st.error(str(exc))
        if nonce:
            st.rerun()
    stored = st.session_state.get("poster_reading")
    if not stored:
        return
    if ready and stored["request_id"] != fingerprint(cooked, goal):
        st.info("사진 또는 준비 조건이 바뀌었어요. 다시 분석하면 새 조건을 반영합니다.")
        return
    data = stored["data"]
    st.divider()
    st.subheader("읽은 내용과 준비 방향")
    st.table([{"항목": key, "내용": data["result"].get(key, "확인 불가")} for key in FIELDS])
    facts, suggestions = st.columns(2)
    with facts:
        st.markdown("#### 사진에서 읽은 사실")
        for fact in data.get("visible_facts", []):
            st.text(fact)
    with suggestions:
        st.markdown("#### AI의 준비 제안")
        for suggestion in data.get("preparation", []):
            st.text(suggestion)
    st.caption(data.get("notice", "원본과 대조해 주세요."))
    usage = data.get("usage", {})
    st.caption(f"실제 사용 토큰 · 입력 {usage.get('input') if usage.get('input') is not None else '확인 불가'} · 출력 {usage.get('output') if usage.get('output') is not None else '확인 불가'}")
    topics = data.get("search_topics", [])
    if topics:
        st.markdown("#### 이어서 읽을 자료")
        st.caption("추천 검색어: " + " / ".join(str(t.get("korean", "")) for t in topics))
        resource_cards(stored.get("resources"), "poster")
    export = {"reading": data, "goal": stored["goal"], "resources": stored.get("resources")}
    st.download_button("포스터 리서치 노트 저장 · JSON", json.dumps(export, ensure_ascii=False, indent=2),
        "PRISM_poster_research.json", "application/json", key="save_poster_reading", on_click="ignore")


def discovery_workspace(url, code, error, api):
    st.subheader("지금 필요한 책과 논문 찾기")
    st.caption("포스터 분석에서 나온 검색어를 이어 쓰거나, 관심 주제로 직접 찾아보세요. 검색에는 Gemini를 호출하지 않습니다.")
    query = st.text_input("주제·도서명·저자", max_chars=160, key="resource_query", placeholder="예: machine learning accessibility")
    kind = st.selectbox("검색 범위", ["도서와 논문", "도서", "논문"], key="resource_kind")
    if st.button("자료 검색", disabled=bool(error) or len(query.strip()) < 2, key="search_resources"):
        try:
            with st.spinner("실제 서지 정보를 검색하고 있어요…"):
                data = api(url, code, "/resources", {"query": query.strip(),
                    "kind": {"도서와 논문": "all", "도서": "books", "논문": "papers"}[kind]})
            st.session_state["manual_resources"] = data
        except ValueError as exc:
            st.error(str(exc))
    data = st.session_state.get("manual_resources") or st.session_state.get("poster_resources")
    if data:
        st.caption("검색한 주제: " + data.get("query", ""))
        resource_cards(data, "manual")
    else:
        st.info("주제를 검색하거나 포스터를 먼저 분석해 보세요.")
