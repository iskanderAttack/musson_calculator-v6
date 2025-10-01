import streamlit as st
import math
import pandas as pd
import altair as alt

# --- КОНСТАНТЫ И ИНЖЕНЕРНЫЕ ДАННЫЕ ---

# Коэффициенты теплопроводности материалов, Вт/(м·К)
MATERIALS = {
    "Кирпич": 0.81,
    "Газоблок": 0.12,
    "Дерево (брус)": 0.18,
    "Сэндвич-панель": 0.04,
    "Минеральная вата": 0.045, # Усредненное значение для базальтовой ваты
    "OSB": 0.13,
    "Профнастил (сталь)": 58.0 # Высокая, но его толщина мала
}

# Тепловое сопротивление поверхностей (для более точного расчета)
R_SI = 0.13  # Внутренняя поверхность, (м²·К)/Вт
R_SE = 0.04  # Внешняя поверхность, (м²·К)/Вт

# Модели печей "Муссон" с обновленными параметрами
MUSSON_MODELS = {
    "Муссон 300":  {"volume_l": 77,  "duct_count": 2, "duct_diameter_mm": 133},
    "Муссон 600":  {"volume_l": 125, "duct_count": 3, "duct_diameter_mm": 133},
    "Муссон 1000": {"volume_l": 200, "duct_count": 3, "duct_diameter_mm": 133},
    "Муссон 1500": {"volume_l": 311, "duct_count": 4, "duct_diameter_mm": 133},
    "Муссон 2000": {"volume_l": 467, "duct_count": 4, "duct_diameter_mm": 159},
}

# Плотность и низшая теплотворная способность древесины
WOOD_TYPES = {
    "Хвойные (сосна, ель)": {"density": 350, "q_mj_kg": 17.0},
    "Берёза":               {"density": 450, "q_mj_kg": 18.0},
    "Дуб":                  {"density": 550, "q_mj_kg": 19.5},
}


# --- ИНЖЕНЕРНЫЕ РАСЧЕТЫ ---

def calculate_wall_r_value(material_type, wall_thickness_m, min_wool_thickness_m=0.05):
    """
    Рассчитывает полное термическое сопротивление стены (R-value).
    Учитывает многослойную конструкцию для минеральной ваты.
    """
    if material_type == "Минеральная вата с обшивкой":
        # R = R_osb + R_wool + R_steel
        r_osb = 0.009 / MATERIALS["OSB"]
        r_wool = min_wool_thickness_m / MATERIALS["Минеральная вата"]
        r_steel = 0.0005 / MATERIALS["Профнастил (сталь)"] # Толщина профнастила ~0.5 мм
        r_layers = r_osb + r_wool + r_steel
    else:
        lambda_wall = MATERIALS.get(material_type, 0.81)
        r_layers = wall_thickness_m / lambda_wall

    # Добавляем сопротивление поверхностей для более точного расчета
    return R_SI + r_layers + R_SE


def calculate_heat_loss(area, height, wall_r_value, floor_r_value, ceiling_r_value, t_in, t_out):
    """
    Рассчитывает общие теплопотери помещения через стены, пол и потолок.
    """
    delta_t = t_in - t_out
    if delta_t <= 0:
        return 0

    # Расчет площадей
    perimeter = 2 * (math.sqrt(area) + math.sqrt(area)) # Принимаем помещение квадратным для простоты
    wall_area = perimeter * height
    floor_area = area
    ceiling_area = area

    # Теплопотери через каждую конструкцию, Вт
    q_walls = wall_area * delta_t / wall_r_value
    q_floor = floor_area * delta_t / floor_r_value
    q_ceiling = ceiling_area * delta_t / ceiling_r_value

    total_q_w = q_walls + q_floor + q_ceiling
    return total_q_w / 1000  # Переводим в кВт


def get_furnace_power_curve(volume_l, fill_fraction, wood_type, efficiency, burn_hours):
    """
    Рассчитывает кривую падения мощности печи во времени.
    Моделирует пиковую мощность в начале и плавное затухание.
    """
    vol_m3 = volume_l / 1000
    filled_vol_m3 = vol_m3 * fill_fraction
    m_wood = filled_vol_m3 * WOOD_TYPES[wood_type]["density"]
    q_fuel_mj = m_wood * WOOD_TYPES[wood_type]["q_mj_kg"]
    
    total_kwh = (q_fuel_mj / 3.6) * efficiency

    # Моделируем пиковую мощность в 2 раза выше средней для более реалистичной кривой
    # Интеграл мощности по времени равен общей энергии
    # Для линейно убывающей мощности P_peak = 2 * P_avg
    avg_power_kw = total_kwh / burn_hours if burn_hours > 0 else 0
    peak_power_kw = avg_power_kw * 2

    time_points = [i * 0.5 for i in range(int(burn_hours * 2) + 1)]
    power_points = []
    for t in time_points:
        # Линейная интерполяция от пика до нуля
        power = peak_power_kw * (1 - t / burn_hours)
        power_points.append(max(0, power))

    return time_points, power_points, total_kwh


def generate_report(params, heat_loss_kw, recommended_model, cascade_option, refuel_time):
    """Генерирует текстовый отчет для скачивания."""
    report = f"""
# Отчет по подбору печи "Муссон"

## 1. Параметры помещения и климата
- Площадь помещения: {params['area']} м²
- Высота потолков: {params['height']} м
- Объем помещения: {params['area'] * params['height']:.1f} м³
- Материал стен: {params['material']}
- Толщина основной стены / утеплителя: {params['thickness_cm']} см
- Желаемая внутренняя температура: {params['t_in']} °C
- Наружная температура: {params['t_out']} °C

## 2. Расчетные теплопотери
- **Требуемая мощность для компенсации теплопотерь: {heat_loss_kw:.2f} кВт**
- С учетом запаса 20%: **{heat_loss_kw * 1.2:.2f} кВт**

## 3. Параметры топки
- Порода древесины: {params['wood_type']}
- Заполнение топки: {params['fill_fraction']*100:.0f}%
- КПД печи: {params['efficiency']*100:.0f}%
- Продолжительность горения закладки: {params['burn_hours']} ч

## 4. Рекомендации
"""
    if recommended_model:
        report += f"- **Рекомендуемая модель: {recommended_model}**\n"
        report += f"- **Рекомендация по топке:** Для поддержания стабильной температуры ~{params['t_in']}°C, рекомендуется производить следующую закладку дров **каждые {refuel_time:.1f} ч.**\n"
    else:
        report += "- Ни одна из одиночных моделей не справляется с теплопотерями.\n"

    if cascade_option:
        report += f"- **Каскадное решение:** В качестве альтернативы можно использовать {cascade_option}.\n"

    report += "\n---\n*Этот расчет является предварительным. Для точного подбора оборудования рекомендуется консультация со специалистом и проведение детального теплотехнического аудита объекта.*"
    return report

# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(layout="wide")
st.title("Теплотехнический калькулятор подбора печи Муссон")
st.write("Этот калькулятор поможет вам подобрать оптимальную модель печи для вашего помещения, основываясь на инженерных расчетах теплопотерь и моделировании процесса горения.")


# --- Ввод данных в сайдбаре ---
st.sidebar.header("1. Параметры помещения")
area = st.sidebar.number_input("Площадь помещения (м²)", min_value=4.0, max_value=2000.0, value=100.0, step=1.0)
height = st.sidebar.number_input("Высота потолков (м)", min_value=1.6, max_value=6.0, value=2.5, step=0.1)
material_type = st.sidebar.selectbox("Материал стен", ["Кирпич", "Газоблок", "Дерево (брус)", "Сэндвич-панель", "Минеральная вата с обшивкой"])

if material_type == "Минеральная вата с обшивкой":
    min_wool_thickness_cm = st.sidebar.select_slider(
        "Толщина утеплителя (минваты), см",
        options=[5, 10, 15, 20],
        value=10
    )
    thickness_cm = min_wool_thickness_cm
else:
    thickness_cm = st.sidebar.slider("Толщина стен (см)", min_value=5, max_value=100, value=40, step=1)

st.sidebar.header("2. Климатические условия")
t_in = st.sidebar.slider("Желаемая внутренняя температура (°C)", 15, 70, 22)
t_out = st.sidebar.slider("Наружная температура зимой (°C)", -50, 10, -20)

st.sidebar.header("3. Параметры топки")
wood_type = st.sidebar.selectbox("Порода древесины", list(WOOD_TYPES.keys()))
fill_fraction = st.sidebar.slider("Процент заполнения топки", 50, 100, 80) / 100
efficiency = st.sidebar.slider("КПД печи и системы (%)", 70, 95, 85) / 100
burn_hours = st.sidebar.selectbox("Время горения одной закладки (ч)", [2, 4, 6, 8, 12, 18, 24], index=3)


# --- Выполнение расчетов ---
wall_thickness_m = thickness_cm / 100
min_wool_thickness_m = thickness_cm / 100 if material_type == "Минеральная вата с обшивкой" else 0.05

wall_r_val = calculate_wall_r_value(material_type, wall_thickness_m, min_wool_thickness_m)
# Упрощенные, но разумные R-value для пола и потолка. Можно сделать их настраиваемыми.
floor_r_val = 2.5 # Утепленный пол по грунту
ceiling_r_val = 3.5 # Утепленное чердачное перекрытие

heat_loss_kw = calculate_heat_loss(area, height, wall_r_val, floor_r_val, ceiling_r_val, t_in, t_out)
required_power_with_margin = heat_loss_kw * 1.2 # Запас 20%

# --- Отображение результатов ---
st.header("Результаты анализа")
col1, col2 = st.columns(2)
with col1:
    st.subheader("Требуемая мощность")
    st.metric(label="Расчетные теплопотери помещения", value=f"{heat_loss_kw:.2f} кВт")
    st.metric(label="Мощность с запасом 20%", value=f"{required_power_with_margin:.2f} кВт")
    st.info("Это мощность, которую система отопления должна постоянно поставлять для поддержания заданной температуры.")

all_models_data = []
recommended_model = None
best_model_avg_power = 0

for model_name, params in MUSSON_MODELS.items():
    time_pts, power_pts, total_kwh = get_furnace_power_curve(params["volume_l"], fill_fraction, wood_type, efficiency, burn_hours)
    avg_power = total_kwh / burn_hours if burn_hours > 0 else 0
    
    all_models_data.append({
        "model": model_name,
        "time": time_pts,
        "power": power_pts,
        "avg_power": avg_power
    })
    
    # Логика выбора лучшей модели
    if avg_power >= required_power_with_margin and avg_power > best_model_avg_power:
        recommended_model = model_name
        best_model_avg_power = avg_power

with col2:
    st.subheader("Рекомендации")
    if recommended_model:
        st.success(f"**Рекомендуемая модель: {recommended_model}**")
        st.write(f"Средняя мощность этой печи ({best_model_avg_power:.2f} кВт) при заданных условиях достаточна для отопления вашего помещения.")
    else:
        st.error("**Ни одна из моделей не подходит.**")
        st.write("Средняя мощность даже самой производительной печи недостаточна. Попробуйте выбрать более плотную древесину, увеличить % заполнения или рассмотрите каскадное решение.")

    # Логика каскадного решения
    cascade_option = None
    if not recommended_model and heat_loss_kw > 0:
        # Попробуем найти каскад из самой мощной модели
        most_powerful = max(all_models_data, key=lambda x: x['avg_power'])
        if most_powerful['avg_power'] > 0:
            num_furnaces = math.ceil(required_power_with_margin / most_powerful['avg_power'])
            if num_furnaces > 1:
                cascade_option = f"{num_furnaces} шт. x {most_powerful['model']}"
                st.warning(f"**Каскадное решение:** Для покрытия теплопотерь можно установить **{cascade_option}**.")


st.header("График эффективности горения")

if recommended_model:
    rec_model_data = next(item for item in all_models_data if item["model"] == recommended_model)
    
    # Находим время для следующей закладки
    refuel_time = 0
    for t, p in zip(rec_model_data['time'], rec_model_data['power']):
        if p >= required_power_with_margin:
            refuel_time = t
        else:
            break
            
    with col2:
         st.subheader("Периодичность топки")
         st.info(f"Для поддержания температуры, вам необходимо будет подкладывать дрова примерно **каждые {refuel_time:.1f} часа**.")


    # Создание датафрейма для графика
    source = pd.DataFrame({
        'Время (часы)': rec_model_data['time'],
        'Мощность печи (кВт)': rec_model_data['power']
    })

    # График мощности печи
    power_chart = alt.Chart(source).mark_area(
        line={'color':'darkgreen'},
        color=alt.Gradient(
            gradient='linear',
            stops=[alt.GradientStop(color='white', offset=0), alt.GradientStop(color='darkgreen', offset=1)],
            x1=1, x2=1, y1=1, y2=0
        ),
        interpolate='monotone',
        opacity=0.7
    ).encode(
        x=alt.X('Время (часы):Q', axis=alt.Axis(title='Время с момента закладки, ч')),
        y=alt.Y('Мощность печи (кВт):Q', axis=alt.Axis(title='Тепловая мощность, кВт'))
    ).properties(
        title=f'Снижение мощности печи "{recommended_model}"'
    )
    
    # Линия теплопотерь
    heat_loss_line = alt.Chart(pd.DataFrame({'y': [required_power_with_margin]})).mark_rule(color='red', strokeDash=[5,5], size=2).encode(y='y')
    
    heat_loss_text = heat_loss_line.mark_text(
        align='left',
        baseline='bottom',
        text=f'Требуемая мощность ({required_power_with_margin:.2f} кВт)',
        dx=7,
        dy=-7,
        color='red'
    )
    
    st.altair_chart(power_chart + heat_loss_line + heat_loss_text, use_container_width=True)
    st.markdown("""
    **Как читать этот график:**
    - **Зеленая область** — это мощность, которую выдает ваша печь. Она максимальна сразу после растопки и постепенно падает.
    - **Красная пунктирная линия** — это теплопотери вашего здания. Чтобы в помещении было тепло, зеленая область должна быть выше этой линии.
    - **Точка пересечения** — это момент, когда печь перестает справляться с обогревом, и температура в помещении начнет медленно снижаться. Это и есть сигнал для следующей закладки дров.
    """)

else:
    st.warning("График не может быть построен, так как не выбрана подходящая модель. Измените параметры.")


# --- Генерация отчета ---
st.header("Скачать полный отчет")
report_params = {
    'area': area, 'height': height, 'material': material_type,
    'thickness_cm': thickness_cm, 't_in': t_in, 't_out': t_out,
    'wood_type': wood_type, 'fill_fraction': fill_fraction,
    'efficiency': efficiency, 'burn_hours': burn_hours
}
final_report = generate_report(report_params, heat_loss_kw, recommended_model, cascade_option, refuel_time if recommended_model else 0)

st.download_button(
    label="📥 Скачать отчет (.txt)",
    data=final_report,
    file_name=f"Musson_Report_A{area}_H{height}_T{t_out}.txt",
    mime="text/plain"
)
