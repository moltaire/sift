from dateutil import tz
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fumble.store import (
    DB_PATH,
    delete_assessment,
    init_db,
    load_assessments,
    update_rating,
)

st.set_option("client.toolbarMode", "viewer")
st.set_page_config(page_title="Fumble", layout="wide", page_icon="💘")
st.title("💘 Fumble")

# Read focus mode from the widget key (updated by Streamlit before the script runs on toggle
# interaction), falling back to a non-widget key for runs where the toggle wasn't rendered
# (Streamlit clears widget-keyed session state when the widget is hidden).
_focus_mode = st.session_state.get(
    "focus_mode", st.session_state.get("_focus_persisted", False)
)

init_db()


@st.cache_data
def _load_assessments(mtime: float | None):
    """Cache keyed on DB mtime — stale cache is automatically bypassed when the file changes."""
    return load_assessments()


@st.fragment(run_every=30)
def _db_watcher():
    mtime = DB_PATH.stat().st_mtime if DB_PATH.exists() else None
    prev = st.session_state.get("_db_mtime")
    st.session_state["_db_mtime"] = mtime
    if prev is not None and mtime != prev:
        st.rerun()


_db_watcher()
assessments = _load_assessments(st.session_state.get("_db_mtime"))

if not assessments:
    st.info("No listings yet. Run fumblebee first.")
    st.stop()

with open("resources/sources.toml", "rb") as _f:
    import tomllib as _tomllib

    _sources = _tomllib.load(_f)["sources"]
SOURCE_DISPLAY = {s["name"]: s.get("display", s["name"].title()) for s in _sources}
SOURCE_DISPLAY.setdefault("manual-test", "Manual")
SUGGESTION_ICON = {"apply": "🟢", "consider": "🟡", "skip": "🔴"}
FIT_ICON = {"high": "🟢", "medium": "🟡", "low": "🔴"}
GAP_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
RATING_ICON = {"new": "📬", "superliked": "🌟", "liked": "👍", "disliked": "👎"}

SUGGESTION_LABELS = {
    f"{SUGGESTION_ICON[v]} {v.title()}": v for v in ["apply", "consider", "skip"]
}
FIT_LABELS = {f"{FIT_ICON[v]} {v}": v for v in ["high", "medium", "low"]}
GAP_LABELS = {
    f"{GAP_ICON[v]} {v}": v for v in ["low", "medium", "high"]
}  # low risk first

# Named views: label → rating values to include
VIEWS = {
    "📬 Inbox": ["new"],
    "⭐ Saved": ["superliked", "liked"],
    "👎 Hidden": ["disliked"],
    "✨ All": ["new", "superliked", "liked", "disliked"],
}
_DEFAULT_VIEW = "📬 Inbox"

# Refinement defaults = all options selected (no filtering)
_REFINE_DEFAULTS: dict = {
    "refine_suggestion": list(SUGGESTION_LABELS),
    "refine_domain_fit": list(FIT_LABELS),
    "refine_role_fit": list(FIT_LABELS),
    "refine_gap_risk": list(GAP_LABELS),
    "filter_employers": [],
    "filter_titles": [],
    "filter_scraped_after": None,
    "filter_scraped_before": None,
    "filter_assessed_after": None,
    "filter_assessed_before": None,
}

raw_df = pd.DataFrame([a.model_dump() for a in assessments])
raw_df["scraped_at"] = pd.to_datetime(raw_df["scraped_at"], utc=True).dt.tz_convert(tz.tzlocal()).dt.strftime(
    "%Y-%m-%d %H:%M"
)
raw_df["assessed_at"] = pd.to_datetime(raw_df["assessed_at"], utc=True).dt.tz_convert(tz.tzlocal()).dt.strftime(
    "%Y-%m-%d %H:%M"
)

df = raw_df.copy()
df["suggestion"] = df["suggestion"].map(lambda v: f"{SUGGESTION_ICON[v]} {v.title()}")
_DOT = {"high": "🟢", "medium": "🟡", "low": "🔴"}
_DOT_INV = {"low": "🟢", "medium": "🟡", "high": "🔴"}
df["domain_fit"] = raw_df["domain_fit"].map(_DOT)
df["role_fit"] = raw_df["role_fit"].map(_DOT)
df["gap_risk"] = raw_df["gap_risk"].map(_DOT_INV)
df["source"] = df["source"].map(lambda v: SOURCE_DISPLAY.get(v, v.title()))
df["rating"] = raw_df["rating"].map(lambda v: RATING_ICON.get(v, "🆕"))

# Detect view change or explicit reset → clear refinement filters before widgets render
# Use a separate non-widget key so the view survives focus mode (widgets clear state when hidden)
_current_view = st.session_state.get("_view_persisted", _DEFAULT_VIEW)
_prev_view = st.session_state.get("_prev_view")
if st.session_state.pop("_reset_refinements", False) or (
    _prev_view is not None and _current_view != _prev_view
):
    for k, v in _REFINE_DEFAULTS.items():
        st.session_state[k] = v
    st.session_state.pop("selected_url", None)
if _prev_view is None or _current_view != _prev_view:
    st.session_state["_prev_view"] = _current_view

if not _focus_mode:
    # --- View switcher + refine popover + search (single row) ---
    _refine_active = (
        set(st.session_state.get("refine_suggestion", list(SUGGESTION_LABELS)))
        != set(SUGGESTION_LABELS)
        or set(st.session_state.get("refine_domain_fit", list(FIT_LABELS)))
        != set(FIT_LABELS)
        or set(st.session_state.get("refine_role_fit", list(FIT_LABELS)))
        != set(FIT_LABELS)
        or set(st.session_state.get("refine_gap_risk", list(GAP_LABELS)))
        != set(GAP_LABELS)
        or bool(st.session_state.get("filter_employers"))
        or bool(st.session_state.get("filter_titles"))
        or st.session_state.get("filter_scraped_after") is not None
        or st.session_state.get("filter_scraped_before") is not None
        or st.session_state.get("filter_assessed_after") is not None
        or st.session_state.get("filter_assessed_before") is not None
    )

    _vcol, _right = st.columns([2, 1], gap="large")
    with _right:
        _rcol, _scol = st.columns([1, 4], gap="small")
    with _vcol:
        view = (
            st.segmented_control(
                "View",
                options=list(VIEWS),
                default=_current_view,
                key="view",
                selection_mode="single",
                label_visibility="collapsed",
            )
            or _DEFAULT_VIEW
        )
        st.session_state["_view_persisted"] = view
        _current_view = view
    with _rcol:
        with st.popover(
            ":material/filter_alt:" if _refine_active else ":material/filter_alt_off:",
            width="stretch",
        ):
            _fc1, _fc2, _fc3, _fc4 = st.columns(4)
            with _fc1:
                st.pills(
                    "Suggestion",
                    options=list(SUGGESTION_LABELS),
                    default=list(SUGGESTION_LABELS),
                    key="refine_suggestion",
                    selection_mode="multi",
                )
            with _fc2:
                st.pills(
                    "Domain Fit",
                    options=list(FIT_LABELS),
                    default=list(FIT_LABELS),
                    key="refine_domain_fit",
                    selection_mode="multi",
                )
            with _fc3:
                st.pills(
                    "Role Fit",
                    options=list(FIT_LABELS),
                    default=list(FIT_LABELS),
                    key="refine_role_fit",
                    selection_mode="multi",
                )
            with _fc4:
                st.pills(
                    "Gap Risk",
                    options=list(GAP_LABELS),
                    default=list(GAP_LABELS),
                    key="refine_gap_risk",
                    selection_mode="multi",
                )

            employers = sorted([e for e in raw_df["employer"].unique() if e])
            job_titles = sorted([t for t in raw_df["job_title"].unique() if t])
            _ec1, _ec2 = st.columns(2)
            with _ec1:
                if employers:
                    st.multiselect(
                        "Employer",
                        options=employers,
                        default=None,
                        placeholder="Filter by employer",
                        key="filter_employers",
                    )
            with _ec2:
                if job_titles:
                    st.multiselect(
                        "Job Title",
                        options=job_titles,
                        default=None,
                        placeholder="Filter by job title",
                        key="filter_titles",
                    )

            _dc1, _dc2, _dc3, _dc4 = st.columns(4)
            with _dc1:
                st.date_input(
                    "Scraped after",
                    value=st.session_state.get("filter_scraped_after"),
                    key="filter_scraped_after",
                )
            with _dc2:
                st.date_input(
                    "Scraped before",
                    value=st.session_state.get("filter_scraped_before"),
                    key="filter_scraped_before",
                )
            with _dc3:
                st.date_input(
                    "Assessed after",
                    value=st.session_state.get("filter_assessed_after"),
                    key="filter_assessed_after",
                )
            with _dc4:
                st.date_input(
                    "Assessed before",
                    value=st.session_state.get("filter_assessed_before"),
                    key="filter_assessed_before",
                )

            if st.button("Reset refinements", use_container_width=True):
                st.session_state["_reset_refinements"] = True
                st.rerun()
    with _scol:
        search = st.text_input(
            "Search",
            placeholder="Employer, job title, keyword...",
            key="filter_search",
            label_visibility="collapsed",
        )
else:
    search = st.session_state.get("filter_search", "")

# --- Apply filters ---
# Read from session state — popover widgets only run when open, toggle hides them entirely
view = _current_view
_suggestion_keys = st.session_state.get("refine_suggestion") or list(SUGGESTION_LABELS)
_domain_keys = st.session_state.get("refine_domain_fit") or list(FIT_LABELS)
_role_keys = st.session_state.get("refine_role_fit") or list(FIT_LABELS)
_gap_keys = st.session_state.get("refine_gap_risk") or list(GAP_LABELS)

view_ratings = VIEWS.get(view, VIEWS[_DEFAULT_VIEW])
suggestions = [SUGGESTION_LABELS[l] for l in _suggestion_keys]
domain_fits = [FIT_LABELS[l] for l in _domain_keys]
role_fits = [FIT_LABELS[l] for l in _role_keys]
gap_risks = [GAP_LABELS[l] for l in _gap_keys]
selected_employers = st.session_state.get("filter_employers") or []
selected_titles = st.session_state.get("filter_titles") or []
scraped_after = st.session_state.get("filter_scraped_after")
scraped_before = st.session_state.get("filter_scraped_before")
assessed_after = st.session_state.get("filter_assessed_after")
assessed_before = st.session_state.get("filter_assessed_before")

mask = (
    raw_df["rating"].isin(view_ratings)
    & raw_df["suggestion"].isin(suggestions)
    & raw_df["domain_fit"].isin(domain_fits)
    & raw_df["role_fit"].isin(role_fits)
    & raw_df["gap_risk"].isin(gap_risks)
)
if selected_employers:
    mask &= raw_df["employer"].isin(selected_employers)
if selected_titles:
    mask &= raw_df["job_title"].isin(selected_titles)
if scraped_after:
    mask &= raw_df["scraped_at"] >= scraped_after.strftime("%Y-%m-%d")
if scraped_before:
    mask &= raw_df["scraped_at"] <= scraped_before.strftime("%Y-%m-%d 23:59")
if assessed_after:
    mask &= raw_df["assessed_at"] >= assessed_after.strftime("%Y-%m-%d")
if assessed_before:
    mask &= raw_df["assessed_at"] <= assessed_before.strftime("%Y-%m-%d 23:59")
if search:
    sl = search.lower()
    mask &= (
        raw_df["employer"].str.lower().str.contains(sl, na=False)
        | raw_df["job_title"].str.lower().str.contains(sl, na=False)
        | raw_df["reasoning"].str.lower().str.contains(sl, na=False)
        | raw_df["listing_text"].str.lower().str.contains(sl, na=False)
    )

filtered = df[mask].reset_index(drop=True)
filtered_raw = raw_df[mask].reset_index(drop=True)

if _current_view == "⭐ Saved":
    _fit_ord = {"high": 0, "medium": 1, "low": 2}
    _sug_ord = {"apply": 0, "consider": 1, "skip": 2}
    _gap_ord = {"low": 0, "medium": 1, "high": 2}
    _sort_keys = pd.DataFrame(
        {
            "rating": filtered_raw["rating"].map({"superliked": 0, "liked": 1}),
            "suggestion": filtered_raw["suggestion"].map(_sug_ord),
            "scraped_at": filtered_raw["scraped_at"],
            "domain_fit": filtered_raw["domain_fit"].map(_fit_ord),
            "role_fit": filtered_raw["role_fit"].map(_fit_ord),
            "gap_risk": filtered_raw["gap_risk"].map(_gap_ord),
            "employer": filtered_raw["employer"].str.lower().fillna(""),
        }
    )
    _order = _sort_keys.sort_values(
        [
            "rating",
            "suggestion",
            "scraped_at",
            "domain_fit",
            "role_fit",
            "gap_risk",
            "employer",
        ],
        ascending=[True, True, False, True, True, True, True],
        kind="stable",
    ).index
    filtered = filtered.iloc[_order].reset_index(drop=True)
    filtered_raw = filtered_raw.iloc[_order].reset_index(drop=True)

# --- Table (hidden in focus mode) ---
TABLE_COLS = [
    "rating",
    "suggestion",
    "employer",
    "job_title",
    "domain_fit",
    "role_fit",
    "gap_risk",
    "scraped_at",
    "assessed_at",
    "url",
]

selected_url = st.session_state.get("selected_url")

# Auto-select first visible row if nothing is selected
if not selected_url and not filtered_raw.empty:
    selected_url = filtered_raw.iloc[0]["url"]
    st.session_state["selected_url"] = selected_url

if not _focus_mode:
    if filtered.empty:
        _empty_msg = (
            "No liked or superliked listings yet. Rate some listings and they will appear here."
            if _current_view == "⭐ Saved"
            else (
                "No disliked listings yet. Rate some listings and they will appear here."
                if _current_view == "👎 Hidden"
                else "You're all caught up! Check out your ⭐ Saved jobs, or run fumblebee to fetch new ones."
            )
        )
        st.info(_empty_msg)
        selected_url = None
    else:
        _ROW_H = 35
        _HEADER_H = 38
        table_height = min(
            len(filtered) * _ROW_H + _HEADER_H, 280 if selected_url else 560
        )

        selection = st.dataframe(
            filtered[TABLE_COLS],
            column_config={
                "rating": st.column_config.TextColumn("", width=15),
                "suggestion": st.column_config.TextColumn(
                    "Suggestion",
                    help="LLM recommendation: apply, consider, or skip. Advisory only.",
                ),
                "employer": st.column_config.TextColumn("Employer"),
                "job_title": st.column_config.TextColumn("Job Title"),
                "domain_fit": st.column_config.TextColumn(
                    "D",
                    help="Domain fit: 🟢 high · 🟡 medium · 🔴 low",
                    width=15,
                ),
                "role_fit": st.column_config.TextColumn(
                    "R",
                    help="Role fit: 🟢 high · 🟡 medium · 🔴 low",
                    width=15,
                ),
                "gap_risk": st.column_config.TextColumn(
                    "G",
                    help="Gap: 🟢 low · 🟡 medium · 🔴 high",
                    width=15,
                ),
                "scraped_at": st.column_config.TextColumn(
                    "Scraped", help="When the listing was fetched"
                ),
                "assessed_at": st.column_config.TextColumn(
                    "Assessed", help="When the LLM assessment was run"
                ),
                "url": st.column_config.LinkColumn(
                    "Link",
                    display_text="https?://(?:[a-zA-Z0-9-]+\\.)*([a-zA-Z0-9-]+\\.[a-zA-Z]{2,})",
                ),
            },
            width="stretch",
            hide_index=True,
            height=table_height,
            selection_mode="single-row",
            on_select="rerun",
        )

        selected_rows = selection.selection.rows
        if selected_rows and not st.session_state.pop("_from_nav", False):
            clicked_url = filtered_raw.iloc[selected_rows[0]]["url"]
            if clicked_url != selected_url:
                st.session_state["selected_url"] = clicked_url
                selected_url = clicked_url

        st.caption(f"{len(filtered)} of {len(df)} listings")
else:
    st.session_state.pop("_from_nav", None)
    if filtered_raw.empty:
        st.session_state["focus_mode"] = False
        st.session_state["_focus_persisted"] = False
        st.rerun()


# --- Detail panel ---
if selected_url:
    matches = raw_df[raw_df["url"] == selected_url]
    if matches.empty:
        st.session_state.pop("selected_url", None)
    else:
        row = matches.iloc[0]

        # Prev / Next + quick-rate navigation row
        _pos = filtered_raw.index[filtered_raw["url"] == selected_url]
        _pos = int(_pos[0]) if len(_pos) else 0
        _total = len(filtered_raw)
        _next_url = filtered_raw.iloc[_pos + 1]["url"] if _pos < _total - 1 else None

        _rating, _nav = st.columns([2, 1], gap="large")
        with _nav:
            _pc, _mc, _nc = st.columns([1, 1, 1])
            with _pc:
                if st.button(
                    "‹",
                    disabled=_pos == 0,
                    use_container_width=True,
                    help="Previous (Keyboard: Left Arrow or J)",
                ):
                    st.session_state["selected_url"] = filtered_raw.iloc[_pos - 1][
                        "url"
                    ]
                    st.session_state["_from_nav"] = True
                    st.rerun()
            with _mc:
                st.caption(
                    f"<p style='text-align:center;padding-top:8px;font-size:0.85rem'>{_pos + 1} / {_total}</p>",
                    unsafe_allow_html=True,
                )
            with _nc:
                if st.button(
                    "›",
                    disabled=_pos >= _total - 1,
                    use_container_width=True,
                    help="Next (Keyboard: Right Arrow or K)",
                ):
                    st.session_state["selected_url"] = filtered_raw.iloc[_pos + 1][
                        "url"
                    ]
                    st.session_state["_from_nav"] = True
                    st.rerun()

        with _rating:
            _hc, _bc, _sc, _, _focus = st.columns([1, 1, 1, 1 / 3, 2 / 3], gap="small")
            _current_rating = row["rating"]
            # Toggle must render before any button that calls st.rerun(),
            # otherwise the RerunException stops the script before it registers.
            with _focus:
                _focus_mode = st.toggle(
                    "Focus",
                    key="focus_mode",
                    value=st.session_state.get("_focus_persisted", False),
                )
                st.session_state["_focus_persisted"] = _focus_mode
            with _sc:
                if st.button(
                    "🌟",
                    type="primary" if _current_rating == "superliked" else "secondary",
                    use_container_width=True,
                    help="Superlike (Keyboard: 3)",
                ):
                    new_r = "new" if _current_rating == "superliked" else "superliked"
                    update_rating(selected_url, new_r)
                    _load_assessments.clear()
                    if _next_url and new_r != "new":
                        st.session_state["selected_url"] = _next_url
                        st.session_state["_from_nav"] = True
                    st.rerun()
            with _bc:
                if st.button(
                    "👍",
                    type="primary" if _current_rating == "liked" else "secondary",
                    use_container_width=True,
                    help="Like (Keyboard: 2)",
                ):
                    new_r = "new" if _current_rating == "liked" else "liked"
                    update_rating(selected_url, new_r)
                    _load_assessments.clear()
                    if _next_url and new_r != "new":
                        st.session_state["selected_url"] = _next_url
                        st.session_state["_from_nav"] = True
                    st.rerun()
            with _hc:
                if st.button(
                    "👎",
                    type="primary" if _current_rating == "disliked" else "secondary",
                    use_container_width=True,
                    help="Dislike (Keyboard: 1)",
                ):
                    new_r = "new" if _current_rating == "disliked" else "disliked"
                    update_rating(selected_url, new_r)
                    _load_assessments.clear()
                    if _next_url and new_r != "new":
                        st.session_state["selected_url"] = _next_url
                        st.session_state["_from_nav"] = True
                    st.rerun()

        # Job header
        col1, col2 = st.columns([2, 1], gap="large")
        with col1:
            st.markdown(f"### {row['job_title']}")
            st.markdown(f"#### {row['employer']}")

            if row.get("job_summary"):
                st.caption(row["job_summary"])

        with col2:
            st.space("stretch")
            source_col, date_col = st.columns(2)
            with source_col:
                _source_label = SOURCE_DISPLAY.get(row["source"], row["source"].title())
                _url = row["url"]
                if _url:
                    st.caption(
                        f"**Source:** {_source_label} [:material/open_in_new:]({_url})",
                        unsafe_allow_html=False,
                    )
                else:
                    st.caption(f"**Source:** {_source_label}")
                st.caption(f"**Model:** {row.get('assessed_model') or 'N/A'}")
            with date_col:
                st.caption(f"**Scraped:** {row['scraped_at']}")
                st.caption(f"**Assessed:** {row['assessed_at']}")
            st.space("stretch")

        # Listing and analysis
        col_listing, col_analysis = st.columns([2, 1], gap="large")

        with col_listing:
            with st.container(border=True):
                if row.get("listing_text"):
                    st.markdown(
                        "<style>"
                        ".fumble-listing { font-size: 0.9rem; }"
                        ".fumble-listing h1, .fumble-listing h2, .fumble-listing h3"
                        "{ font-size: 1rem !important; font-weight: 600; margin: 0.4em 0 0.2em; }"
                        "</style>"
                        "<div class='fumble-listing'>\n\n"
                        + row["listing_text"]
                        + "\n\n</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No listing text available.")
        with col_analysis:

            st.markdown(
                "### {} Suggestion: {}".format(
                    SUGGESTION_ICON.get(row["suggestion"], ""),
                    row["suggestion"].title(),
                )
            )
            st.caption(row["reasoning"])

            st.markdown("#### Fit analysis")
            st.markdown(
                f"**{FIT_ICON.get(row['domain_fit'], '')} Domain fit: {row['domain_fit'].title()}**"
            )
            if row.get("domain_fit_reason"):
                st.caption(row["domain_fit_reason"])
            st.markdown(
                f"**{FIT_ICON.get(row['role_fit'], '')} Role fit: {row['role_fit'].title()}**"
            )
            if row.get("role_fit_reason"):
                st.caption(row["role_fit_reason"])
            st.markdown(
                f"**{GAP_ICON.get(row['gap_risk'], '')} Gap risk: {row['gap_risk'].title()}**"
            )
            if row.get("gap_risk_reason"):
                st.caption(row["gap_risk_reason"])

            with st.expander("Show details", expanded=False):
                fit_areas = row.get("fit_areas") or []
                gaps = row.get("gaps") or []
                SEVERITY_ICON = {"minor": "🟡", "manageable": "🟠", "severe": "🔴"}
                if fit_areas:
                    st.markdown("**Concrete Overlap**")
                    for area in fit_areas:
                        st.caption(f"- {area}")
                if gaps:
                    st.markdown("**Concrete Gaps**")
                    for gap in gaps:
                        icon = SEVERITY_ICON.get(gap.get("severity", ""), "")
                        st.caption(f"- {icon} {gap['description']}")

            st.divider()
            if st.button(
                "Delete listing from database",
                key="delete_btn",
                width="stretch",
                type="secondary",
            ):
                st.session_state["confirm_delete"] = selected_url
            if st.session_state.get("confirm_delete") == selected_url:
                st.warning("This will permanently delete this entry.")
                if st.button(
                    "Confirm delete", key="confirm_btn", width="stretch", type="primary"
                ):
                    delete_assessment(selected_url)
                    _load_assessments.clear()
                    st.session_state.pop("confirm_delete", None)
                    st.session_state.pop("selected_url", None)
                    st.rerun()


# Keyboard shortcuts:
#   j / ← : previous listing      k / → : next listing
#   1: dislike   2: like   3: superlike
#   g i: Inbox   g s: Saved   g h: Hidden   g a: All
# Handler is replaced on every rerun so shortcut changes take effect without a full reload.
components.html(
    """
    <script>
    (function () {
        var win = window.parent;
        if (win._fumble_nav_handler) {
            win.document.removeEventListener('keydown', win._fumble_nav_handler);
        }

        var _gPending = false;
        var _gTimer = null;

        function clickButton(label) {
            var buttons = win.document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].innerText.trim() === label && !buttons[i].disabled) {
                    buttons[i].click();
                    return true;
                }
            }
            return false;
        }

        function clickFocusToggle() {
            var cb = win.document.querySelector('input[type="checkbox"]');
            if (cb) { cb.click(); return true; }
            return false;
        }

        // Click the segmented-control option whose full text contains `fragment`.
        function clickView(fragment) {
            var buttons = win.document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].innerText.trim().toLowerCase().indexOf(fragment) !== -1) {
                    buttons[i].click();
                    return;
                }
            }
        }

        function focusSearch() {
            var inputs = win.document.querySelectorAll('input[type="text"]');
            for (var i = 0; i < inputs.length; i++) {
                if ((inputs[i].placeholder || '').indexOf('Employer') !== -1) {
                    inputs[i].focus();
                    return true;
                }
            }
            return false;
        }

        win._fumble_nav_handler = function (e) {
            var active = win.document.activeElement;

            // Escape always blurs inputs, regardless of other guards
            if (e.key === 'Escape' && active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
                active.blur();
                e.preventDefault();
                return;
            }

            if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;

            // Second key of a g-chord
            if (_gPending) {
                clearTimeout(_gTimer);
                _gPending = false;
                if (e.key === 'i') { clickView('inbox'); e.preventDefault(); return; }
                if (e.key === 's') { clickView('saved'); e.preventDefault(); return; }
                if (e.key === 'h') { clickView('hidden'); e.preventDefault(); return; }
                if (e.key === 'a') { clickView('all');   e.preventDefault(); return; }
                // unrecognised second key — fall through to normal handling
            }

            // g starts a chord
            if (e.key === 'g') {
                _gPending = true;
                _gTimer = setTimeout(function () { _gPending = false; }, 1000);
                e.preventDefault();
                return;
            }

            if (e.key === 'f') { clickFocusToggle(); return; }
            if (e.key === '/') { if (focusSearch()) { e.preventDefault(); } return; }
            var label = null;
            if (e.key === 'ArrowLeft'  || e.key === 'j') label = '\u2039';
            if (e.key === 'ArrowRight' || e.key === 'k') label = '\u203a';
            if (e.key === '3') label = '🌟';
            if (e.key === '2') label = '👍';
            if (e.key === '1') label = '👎';
            if (!label) return;
            clickButton(label);
        };
        win.document.addEventListener('keydown', win._fumble_nav_handler);
    })();
    </script>
    """,
    height=0,
)
