"""
داشبورد تعاملی گزارش روزانه کشاورزی بابامنیر
نسخه بهینه‌شده از نظر عملکرد

اجرا:
    streamlit run babamenir_dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import requests
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# تلاش برای ایمپورت jdatetime
try:
    import jdatetime
    HAS_JDATETIME = True
except ImportError:
    HAS_JDATETIME = False

# -----------------------------
# تنظیمات صفحه
# -----------------------------
st.set_page_config(
    page_title="گزارش روزانه کشاورزی بابامنیر",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS سبک و بدون فونت خارجی (سرعت بارگذاری بالاتر)
st.markdown("""
<style>
    html, body, [class*="css"] {
        font-family: Tahoma, "Segoe UI", Arial, sans-serif !important;
        direction: rtl;
        text-align: right;
    }
    .stMetric { direction: rtl; text-align: center; }
    .stMetric label { direction: rtl; text-align: center; display: block; }
    div[data-testid="stMetricValue"] { direction: ltr; text-align: center; }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a3c34 0%, #2d5a4c 100%);
    }
    section[data-testid="stSidebar"] * { color: #f8f9fa !important; }
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stRadio label { color: #e9ecef !important; }
    h1, h2, h3 { font-family: Tahoma, "Segoe UI", Arial, sans-serif !important; }
</style>
""", unsafe_allow_html=True)

# -----------------------------
# مختصات جغرافیایی
# -----------------------------
LOCATIONS = {
    "بابامنیر": {"lat": 30.07, "lon": 51.52, "name": "بابامنیر", "elev": 950},
    "نورآباد ممسنی": {"lat": 30.11, "lon": 51.52, "name": "نورآباد ممسنی", "elev": 920},
    "ماهور میلاتی": {"lat": 29.95, "lon": 51.45, "name": "ماهور میلاتی", "elev": 1100}
}

# -----------------------------
# توابع کمکی (سبک و بدون side-effect)
# -----------------------------
def weather_code_to_text(code: int) -> str:
    mapping = {
        0: "صاف و آفتابی", 1: "عمدتاً صاف", 2: "نیمه‌ابری", 3: "ابری",
        45: "مه", 48: "مه یخ‌زده",
        51: "باران ریز", 53: "باران ریز متوسط", 55: "باران ریز شدید",
        61: "باران سبک", 63: "باران متوسط", 65: "باران شدید",
        71: "برف سبک", 73: "برف متوسط", 75: "برف شدید",
        80: "رگبار سبک", 81: "رگبار متوسط", 82: "رگبار شدید",
        95: "رعد و برق", 96: "رعد و برق + تگرگ سبک", 99: "رعد و برق + تگرگ شدید"
    }
    return mapping.get(code, "نامشخص")


def wind_direction_to_text(degrees: Optional[float]) -> str:
    if degrees is None:
        return "نامشخص"
    directions = ["شمال", "شمال‌شرقی", "شرق", "جنوب‌شرقی", "جنوب", "جنوب‌غربی", "غرب", "شمال‌غربی"]
    idx = int((degrees + 22.5) % 360 // 45)
    return directions[idx]


def get_shamsi_date() -> str:
    if HAS_JDATETIME:
        now = jdatetime.datetime.now()
        days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
        return f"{days[now.weekday()]} {now.day} {now.j_months_fa[now.month-1]} {now.year}"
    return datetime.now().strftime("%Y-%m-%d")


def get_update_time() -> str:
    if HAS_JDATETIME:
        return jdatetime.datetime.now().strftime("%H:%M")
    return datetime.now().strftime("%H:%M")


# -----------------------------
# دریافت داده با کش قوی (بدون st.error داخل تابع)
# -----------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def get_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """دریافت داده هواشناسی — فقط داده برمی‌گرداند، بدون side-effect"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m", "relative_humidity_2m", "weather_code",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
            "surface_pressure", "apparent_temperature"
        ],
        "hourly": [
            "temperature_2m", "precipitation_probability", "precipitation",
            "weather_code", "wind_speed_10m", "et0_fao_evapotranspiration"
        ],
        "daily": [
            "temperature_2m_max", "temperature_2m_min",
            "precipitation_probability_max", "precipitation_sum",
            "weather_code", "wind_speed_10m_max",
            "et0_fao_evapotranspiration", "uv_index_max",
            "sunrise", "sunset"
        ],
        "timezone": "Asia/Tehran",
        "forecast_days": 7
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        data["_fetched_at"] = datetime.now().isoformat()
        return data
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def get_all_locations_weather() -> Dict[str, Optional[Dict[str, Any]]]:
    """دریافت موازی داده سه منطقه — یک بار و کش می‌شود"""
    results = {}

    def fetch_one(name: str, info: dict):
        return name, get_weather(info["lat"], info["lon"])

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fetch_one, name, info): name
            for name, info in LOCATIONS.items()
        }
        for future in as_completed(futures):
            name, data = future.result()
            results[name] = data
    return results


def generate_recommendations(weather: Dict[str, Any], location: str) -> List[str]:
    if not weather:
        return ["داده هواشناسی در دسترس نیست. لطفاً بعداً تلاش کنید."]

    current = weather.get("current", {})
    daily = weather.get("daily", {})

    temp = current.get("temperature_2m", 20)
    humidity = current.get("relative_humidity_2m", 50)
    wind = current.get("wind_speed_10m", 0)
    precip_prob = daily.get("precipitation_probability_max", [0])[0] if daily else 0
    precip_sum = daily.get("precipitation_sum", [0])[0] if daily else 0
    et0 = daily.get("et0_fao_evapotranspiration", [0])[0] if daily else 0
    code = current.get("weather_code", 0)

    recs = []

    if 8 <= temp <= 22 and precip_prob < 60:
        recs.append(
            f"**کشت غلات:** شرایط دمایی ({temp:.0f}°C) برای ادامه کشت گندم و جو دیم مناسب است. از بذر گواهی‌شده استفاده کنید."
        )
    elif temp < 5:
        recs.append("**هشدار سرما:** دمای پایین است. از کاشت جدید خودداری کنید و مزارع جوان را محافظت کنید.")
    else:
        recs.append(f"**کشت:** دمای فعلی {temp:.0f}°C است. زمان‌بندی کاشت را با پیش‌بینی ۷ روزه تنظیم کنید.")

    if et0 > 4:
        recs.append(f"**آبیاری:** ET₀ حدود {et0:.1f} میلی‌متر است. در مزارع آبی نیاز آبی را جدی بگیرید.")
    elif precip_sum > 5:
        recs.append(f"**بارش:** حدود {precip_sum:.1f} میلی‌متر بارش پیش‌بینی شده. از آبیاری اضافی خودداری کنید.")

    if wind > 15:
        recs.append(f"**سم‌پاشی:** سرعت باد {wind:.0f} km/h است. از سم‌پاشی خودداری کنید.")
    elif humidity > 80 and precip_prob > 40:
        recs.append("**بیماری قارچی:** رطوبت بالا و احتمال بارش، خطر بیماری‌های برگی را افزایش می‌دهد.")
    else:
        recs.append("**سم‌پاشی:** شرایط نسبتاً مناسب است. قبل از سم‌پاشی سرعت باد را چک کنید.")

    recs.append("**کود:** قیمت اوره نوسان شدید دارد. مصرف را بر اساس آزمون خاک تنظیم کنید.")

    if code >= 61:
        recs.append("**عملیات مزرعه:** به دلیل بارش، از ورود ماشین‌آلات سنگین به مزارع خیس خودداری کنید.")

    return recs


# -----------------------------
# سایدبار
# -----------------------------
with st.sidebar:
    st.markdown("### 🌾 دفتر فنی بابامنیر")
    st.markdown("---")

    selected_location = st.selectbox(
        "📍 انتخاب منطقه",
        list(LOCATIONS.keys()),
        index=0
    )

    st.markdown("---")
    page = st.radio(
        "بخش‌های داشبورد",
        [
            "🏠 خلاصه روز",
            "🌤️ هواشناسی زنده",
            "📊 مقایسه مناطق",
            "💰 قیمت نهاده‌ها",
            "🚜 توصیه‌های فنی",
            "📰 اخبار و منابع"
        ],
        index=0
    )

    st.markdown("---")
    st.caption("واتساپ: ۰۹۱۷۶۸۰۸۷۵۵")
    st.caption("ایتا و روبیکا: @a.d3469")
    st.caption("داده: Open-Meteo (کش ۳۰ دقیقه)")
    st.caption(f"ساعت: {get_update_time()}")

# -----------------------------
# دریافت داده (بهینه)
# -----------------------------
loc = LOCATIONS[selected_location]

# فقط وقتی لازم است داده را می‌گیریم
if page in ["🏠 خلاصه روز", "🌤️ هواشناسی زنده", "🚜 توصیه‌های فنی"]:
    with st.spinner("دریافت داده هواشناسی..."):
        weather = get_weather(loc["lat"], loc["lon"])
else:
    weather = None

# -----------------------------
# صفحه خلاصه روز
# -----------------------------
if page == "🏠 خلاصه روز":
    st.title("🌾 گزارش روزانه کشاورزی بابامنیر")
    st.markdown(f"**منطقه:** {selected_location} | **تاریخ:** {get_shamsi_date()}")
    st.markdown("---")

    if weather:
        current = weather["current"]
        daily = weather["daily"]

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("دمای فعلی", f"{current['temperature_2m']:.1f}°C",
                      delta=f"احساس: {current.get('apparent_temperature', current['temperature_2m']):.1f}°C")
        with col2:
            st.metric("حداقل / حداکثر",
                      f"{daily['temperature_2m_min'][0]:.0f} / {daily['temperature_2m_max'][0]:.0f}°C")
        with col3:
            st.metric("رطوبت نسبی", f"{current['relative_humidity_2m']}%")
        with col4:
            st.metric("احتمال بارش", f"{daily['precipitation_probability_max'][0]}%")
        with col5:
            et0_today = daily.get("et0_fao_evapotranspiration", [0])[0]
            st.metric("ET₀", f"{et0_today:.1f} mm")

        wind_dir = wind_direction_to_text(current.get("wind_direction_10m"))
        st.info(
            f"**وضعیت فعلی:** {weather_code_to_text(current['weather_code'])} | "
            f"باد: {current['wind_speed_10m']:.0f} km/h از {wind_dir} | "
            f"تندباد: {current.get('wind_gusts_10m', 0):.0f} km/h"
        )

        # نمودار دما (سبک)
        st.markdown("### 📈 پیش‌بینی دمای ۷ روز آینده")
        fig_temp = go.Figure()
        fig_temp.add_trace(go.Scatter(
            x=daily["time"], y=daily["temperature_2m_max"],
            mode="lines+markers", name="حداکثر",
            line=dict(color="#e74c3c", width=2)
        ))
        fig_temp.add_trace(go.Scatter(
            x=daily["time"], y=daily["temperature_2m_min"],
            mode="lines+markers", name="حداقل",
            line=dict(color="#3498db", width=2),
            fill="tonexty", fillcolor="rgba(52, 152, 219, 0.12)"
        ))
        fig_temp.update_layout(
            height=340, hovermode="x unified",
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", y=1.12)
        )
        st.plotly_chart(fig_temp, use_container_width=True, config={"displayModeBar": False})

        # دو نمودار کنار هم
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("### 🌧️ بارش و احتمال")
            fig_precip = go.Figure()
            fig_precip.add_trace(go.Bar(
                x=daily["time"], y=daily["precipitation_sum"],
                name="بارش (mm)", marker_color="#3498db", opacity=0.8
            ))
            fig_precip.add_trace(go.Scatter(
                x=daily["time"], y=daily["precipitation_probability_max"],
                name="احتمال (%)", yaxis="y2",
                mode="lines+markers", line=dict(color="#e67e22", width=2)
            ))
            fig_precip.update_layout(
                height=280,
                yaxis=dict(title="بارش"),
                yaxis2=dict(title="احتمال", overlaying="y", side="left", range=[0, 100]),
                margin=dict(l=10, r=10, t=20, b=10),
                legend=dict(orientation="h", y=1.15)
            )
            st.plotly_chart(fig_precip, use_container_width=True, config={"displayModeBar": False})

        with col_b:
            st.markdown("### 💨 حداکثر باد")
            fig_wind = px.bar(
                x=daily["time"],
                y=daily.get("wind_speed_10m_max", [0] * 7),
                labels={"x": "تاریخ", "y": "باد (km/h)"}
            )
            fig_wind.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), showlegend=False)
            st.plotly_chart(fig_wind, use_container_width=True, config={"displayModeBar": False})

        st.markdown("### ⚡ نکات سریع امروز")
        for r in generate_recommendations(weather, selected_location)[:3]:
            st.markdown(f"- {r}")
    else:
        st.error("دریافت داده هواشناسی با مشکل مواجه شد. چند لحظه دیگر تلاش کنید.")

# -----------------------------
# صفحه هواشناسی زنده
# -----------------------------
elif page == "🌤️ هواشناسی زنده":
    st.title(f"🌤️ هواشناسی زنده — {selected_location}")

    if weather:
        current = weather["current"]
        daily = weather["daily"]
        hourly = weather.get("hourly", {})

        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("شرایط فعلی")
            st.markdown(f"""
            - **دما:** {current['temperature_2m']:.1f}°C  
            - **احساس واقعی:** {current.get('apparent_temperature', current['temperature_2m']):.1f}°C  
            - **رطوبت:** {current['relative_humidity_2m']}%  
            - **باد:** {current['wind_speed_10m']:.0f} km/h ({wind_direction_to_text(current.get('wind_direction_10m'))})  
            - **تندباد:** {current.get('wind_gusts_10m', 0):.0f} km/h  
            - **وضعیت:** {weather_code_to_text(current['weather_code'])}
            """)
        with col2:
            st.subheader("امروز")
            sunrise = daily.get("sunrise", ["-"])[0][-5:] if daily.get("sunrise") else "-"
            sunset = daily.get("sunset", ["-"])[0][-5:] if daily.get("sunset") else "-"
            st.markdown(f"""
            - **حداقل / حداکثر:** {daily['temperature_2m_min'][0]:.0f} / {daily['temperature_2m_max'][0]:.0f}°C  
            - **احتمال بارش:** {daily['precipitation_probability_max'][0]}%  
            - **بارش:** {daily['precipitation_sum'][0]:.1f} mm  
            - **ET₀:** {daily.get('et0_fao_evapotranspiration', [0])[0]:.1f} mm  
            - **UV حداکثر:** {daily.get('uv_index_max', [0])[0]:.1f}  
            - **طلوع / غروب:** {sunrise} / {sunset}
            """)
        with col3:
            st.subheader("منطقه")
            st.markdown(f"""
            - **عرض:** {loc['lat']}  
            - **طول:** {loc['lon']}  
            - **ارتفاع تقریبی:** ~{loc.get('elev', '—')} متر  
            - **منبع:** Open-Meteo
            """)

        st.markdown("---")
        st.subheader("پیش‌بینی ۷ روز آینده")
        df7 = pd.DataFrame({
            "تاریخ": daily["time"],
            "حداقل": [round(x, 1) for x in daily["temperature_2m_min"]],
            "حداکثر": [round(x, 1) for x in daily["temperature_2m_max"]],
            "احتمال بارش": daily["precipitation_probability_max"],
            "بارش": [round(x, 1) for x in daily["precipitation_sum"]],
            "باد حداکثر": [round(x, 0) for x in daily.get("wind_speed_10m_max", [0] * 7)],
            "ET₀": [round(x, 1) for x in daily.get("et0_fao_evapotranspiration", [0] * 7)],
            "وضعیت": [weather_code_to_text(c) for c in daily["weather_code"]]
        })
        st.dataframe(df7, use_container_width=True, hide_index=True)

        if hourly and "time" in hourly:
            st.markdown("---")
            st.subheader("پیش‌بینی ساعتی (۲۴ ساعت آینده)")
            times = hourly["time"][:24]
            fig_h = go.Figure()
            fig_h.add_trace(go.Scatter(
                x=[t[11:16] for t in times],
                y=hourly["temperature_2m"][:24],
                mode="lines+markers", name="دما (°C)",
                line=dict(color="#e74c3c", width=2)
            ))
            fig_h.add_trace(go.Bar(
                x=[t[11:16] for t in times],
                y=hourly.get("precipitation", [0] * 24)[:24],
                name="بارش (mm)", marker_color="#3498db", opacity=0.55, yaxis="y2"
            ))
            fig_h.update_layout(
                height=320,
                yaxis=dict(title="دما"),
                yaxis2=dict(title="بارش", overlaying="y", side="left", showgrid=False),
                margin=dict(l=10, r=10, t=20, b=10),
                legend=dict(orientation="h", y=1.12),
                hovermode="x unified"
            )
            st.plotly_chart(fig_h, use_container_width=True, config={"displayModeBar": False})

        st.caption("منبع: Open-Meteo | کش ۳۰ دقیقه‌ای")
    else:
        st.error("دریافت داده هواشناسی با مشکل مواجه شد.")

# -----------------------------
# صفحه مقایسه مناطق (بهینه با دریافت موازی)
# -----------------------------
elif page == "📊 مقایسه مناطق":
    st.title("📊 مقایسه سه منطقه تحت پوشش")
    st.markdown("مقایسه زنده بابامنیر، نورآباد ممسنی و ماهور میلاتی")
    st.markdown("---")

    with st.spinner("دریافت همزمان داده سه منطقه..."):
        all_weather = get_all_locations_weather()

    comparison_data = []
    for name, w in all_weather.items():
        if w:
            cur = w["current"]
            dai = w["daily"]
            comparison_data.append({
                "منطقه": name,
                "دما (°C)": round(cur["temperature_2m"], 1),
                "رطوبت (%)": cur["relative_humidity_2m"],
                "باد (km/h)": round(cur["wind_speed_10m"], 0),
                "حداقل": round(dai["temperature_2m_min"][0], 1),
                "حداکثر": round(dai["temperature_2m_max"][0], 1),
                "احتمال بارش": dai["precipitation_probability_max"][0],
                "بارش (mm)": round(dai["precipitation_sum"][0], 1),
                "ET₀": round(dai.get("et0_fao_evapotranspiration", [0])[0], 1),
                "وضعیت": weather_code_to_text(cur["weather_code"])
            })

    if comparison_data:
        st.dataframe(pd.DataFrame(comparison_data), use_container_width=True, hide_index=True)

        st.markdown("### مقایسه دما")
        fig_comp = go.Figure()
        for row in comparison_data:
            fig_comp.add_trace(go.Bar(
                name=row["منطقه"],
                x=["فعلی", "حداقل", "حداکثر"],
                y=[row["دما (°C)"], row["حداقل"], row["حداکثر"]]
            ))
        fig_comp.update_layout(
            barmode="group", height=340,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", y=1.12)
        )
        st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False})
        st.info("تفاوت ارتفاع و موقعیت محلی باعث اختلاف جزئی دما و بارش می‌شود.")
    else:
        st.error("نتوانستیم داده مقایسه‌ای را دریافت کنیم.")

# -----------------------------
# صفحه قیمت نهاده‌ها
# -----------------------------
elif page == "💰 قیمت نهاده‌ها":
    st.title("💰 قیمت روز نهاده‌های کشاورزی")
    st.warning(
        "⚠️ قیمت کودها به‌شدت متغیر است. استعلام محلی از کارگزاری نورآباد و جهاد کشاورزی ممسنی ضروری است."
    )

    st.markdown("#### بذر")
    st.dataframe(pd.DataFrame({
        "نهاده": ["بذر گندم نان گواهی‌شده", "بذر گندم دوروم گواهی‌شده", "بذر جو گواهی‌شده"],
        "قیمت تقریبی (تومان)": ["۶۷٬۰۰۰ – ۷۲٬۰۰۰", "۷۵٬۰۰۰ – ۸۰٬۰۰۰", "۶۵٬۰۰۰ – ۷۲٬۰۰۰"],
        "واحد": ["کیلوگرم", "کیلوگرم", "کیلوگرم"],
        "توضیح": ["با یارانه دیم", "معمولاً بدون یارانه", "با یارانه دیم"]
    }), use_container_width=True, hide_index=True)

    st.markdown("#### کود")
    st.dataframe(pd.DataFrame({
        "نهاده": ["کود اوره (۵۰ک)", "سوپرفسفات تریپل (۵۰ک)", "سولفات پتاسیم (۵۰ک)", "کود کامل NPK"],
        "قیمت تقریبی": ["۳٫۲ – ۳٫۸ میلیون", "۶٫۵ – ۸ میلیون", "۶ – ۷٫۵ میلیون", "متغیر"],
        "واحد": ["کیسه", "کیسه", "کیسه", "کیسه/کیلو"],
        "توضیح": ["نوسان شدید", "بازار آزاد", "بازار آزاد", "بسته به آنالیز"]
    }), use_container_width=True, hide_index=True)

    st.caption("آخرین بازبینی دستی: آبان ۱۴۰۴ | این بخش به‌صورت دستی به‌روزرسانی می‌شود.")

# -----------------------------
# صفحه توصیه‌های فنی
# -----------------------------
elif page == "🚜 توصیه‌های فنی":
    st.title("🚜 توصیه‌های فنی امروز")
    st.markdown(f"**منطقه:** {selected_location} | **تاریخ:** {get_shamsi_date()}")
    st.markdown("---")

    if weather:
        for i, rec in enumerate(generate_recommendations(weather, selected_location), 1):
            st.markdown(f"**{i}.** {rec}")
            st.markdown("")

        st.markdown("---")
        st.subheader("نکات عمومی فصل")
        st.markdown("""
        - استفاده از بذر گواهی‌شده و ضدعفونی‌شده اولویت دارد.
        - قبل از مصرف کود، در صورت امکان آزمون خاک انجام دهید.
        - از ورود ماشین‌آلات به مزرعه در رطوبت بالای خاک خودداری کنید.
        - پایش مستمر آفات و بیماری‌ها توصیه می‌شود.
        """)
    else:
        st.error("برای تولید توصیه‌های دقیق به داده هواشناسی نیاز است.")

# -----------------------------
# صفحه اخبار و منابع
# -----------------------------
elif page == "📰 اخبار و منابع":
    st.title("📰 اخبار و منابع")
    st.markdown("""
    ### منابع هواشناسی
    - **Open-Meteo**: داده زنده بدون نیاز به کلید API
    - به‌روزرسانی خودکار هر ۳۰ دقیقه (کش)

    ### منابع قیمت و اخبار
    - سازمان جهاد کشاورزی استان فارس
    - شرکت خدمات حمایتی کشاورزی
    - خبرگزاری‌های رسمی

    ### تماس
    - واتساپ: ۰۹۱۷۶۸۰۸۷۵۵  
    - ایتا و روبیکا: @a.d3469
    """)
    st.info("این داشبورد بخشی از سامانه اطلاع‌رسانی روزانه دفتر فنی بابامنیر است.")

# -----------------------------
# فوتر
# -----------------------------
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #6c757d; font-size: 0.85em; padding: 0.6rem 0;'>
        🌱 دفتر فنی و خدمات کشاورزی بابامنیر<br>
        واتساپ: ۰۹۱۷۶۸۰۸۷۵۵ | ایتا و روبیکا: @a.d3469<br>
        <small>Open-Meteo • کش ۳۰ دقیقه • نسخه بهینه‌شده</small>
    </div>
    """,
    unsafe_allow_html=True
)
