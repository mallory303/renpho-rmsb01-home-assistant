const METRICS = [
  { key: "weight", label: "Weight", suffix: "weight", improvement: "down" },
  { key: "bmi", label: "BMI", suffix: "bmi", improvement: "down" },
  { key: "body_fat", label: "Body fat", suffix: "body_fat", improvement: "down" },
  { key: "subcutaneous_fat", label: "Subcutaneous fat", suffix: "subcutaneous_fat", improvement: "down" },
  { key: "visceral_fat", label: "Visceral fat", suffix: "visceral_fat", improvement: "down" },
  { key: "body_water", label: "Body water", suffix: "body_water", improvement: "up" },
  { key: "muscle_percentage", label: "Muscle percentage", suffix: "muscle_percentage", improvement: "up" },
  { key: "bone_mass", label: "Bone mass", suffix: "bone_mass", improvement: "up" },
  { key: "basal_metabolic_rate", label: "Basal metabolic rate", suffix: "basal_metabolic_rate", improvement: "up" },
  { key: "protein", label: "Protein", suffix: "protein", improvement: "up" },
  { key: "lean_body_mass", label: "Lean body mass", suffix: "lean_body_mass", improvement: "up" },
  { key: "muscle_mass", label: "Muscle mass", suffix: "muscle_mass", improvement: "up" },
  { key: "body_age", label: "Body age", suffix: "body_age", improvement: "down" },
  { key: "last_measurement", label: "Last measurement", suffix: "last_measurement", improvement: null },
];

const DEFAULT_METRICS = [
  "weight",
  "bmi",
  "body_fat",
  "body_water",
  "muscle_percentage",
  "bone_mass",
  "body_age",
  "last_measurement",
];

const metricByKey = (key) => METRICS.find((metric) => metric.key === key);

function fireEvent(node, type, detail) {
  node.dispatchEvent(new CustomEvent(type, {
    detail,
    bubbles: true,
    composed: true,
  }));
}

class RenphoScaleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._userError = "";
    this._viewError = "";
  }

  static getConfigElement() {
    return document.createElement("renpho-rmsb01-card-editor");
  }

  static getStubConfig(hass) {
    const states = (hass && hass.states) || {};
    const entity = Object.keys(states).find((entityId) => (
      entityId.startsWith("sensor.")
      && entityId.includes("renpho")
      && entityId.endsWith("_weight")
    )) || "sensor.renpho_r_msb01_weight";
    return {
      type: "custom:renpho-rmsb01-card",
      title: "Renpho Scale",
      entity,
      history_days: 30,
      metrics: [...DEFAULT_METRICS],
    };
  }

  static get availableMetrics() {
    return METRICS.map((metric) => ({ ...metric }));
  }

  static entityFor(config, key) {
    const metric = metricByKey(key);
    if (!metric) {
      throw new Error(`Unknown Renpho metric: ${key}`);
    }
    if (config.entities && typeof config.entities[key] === "string") {
      return config.entities[key];
    }
    if (key === "weight") {
      return config.entity;
    }
    const prefix = config.entity.replace(/_weight$/, "");
    return `${prefix}_${metric.suffix}`;
  }

  static userEntityFor(config) {
    if (config.user_entity) {
      return config.user_entity;
    }
    const prefix = config.entity.replace(/^sensor\./, "").replace(/_weight$/, "");
    return `select.${prefix}_user`;
  }

  static viewEntityFor(config) {
    if (config.view_entity) {
      return config.view_entity;
    }
    const prefix = config.entity.replace(/^sensor\./, "").replace(/_weight$/, "");
    return `select.${prefix}_viewed_user`;
  }

  entityForView(key, viewState) {
    const profileEntities = viewState
      && viewState.attributes
      && viewState.attributes.profile_entities;
    const entities = profileEntities && profileEntities[viewState.state];
    return (entities && entities[key]) || RenphoScaleCard.entityFor(this._config, key);
  }

  setConfig(config) {
    if (!config || typeof config.entity !== "string" || !config.entity.startsWith("sensor.")) {
      throw new Error("Select the scale's weight sensor entity.");
    }
    const metrics = config.metrics === undefined ? DEFAULT_METRICS : config.metrics;
    if (!Array.isArray(metrics) || metrics.some((key) => !metricByKey(key))) {
      throw new Error("The metrics list contains an unknown value.");
    }
    const trendDirections = config.trend_directions === undefined ? {} : config.trend_directions;
    if (!trendDirections || typeof trendDirections !== "object" || Array.isArray(trendDirections)) {
      throw new Error("Trend directions must be a metric-to-direction mapping.");
    }
    Object.entries(trendDirections).forEach(([key, direction]) => {
      if (!metricByKey(key) || !["up", "down"].includes(direction)) {
        throw new Error("Each trend direction must use a known metric and up or down.");
      }
    });
    const historyDays = config.history_days === undefined ? 30 : config.history_days;
    if (!Number.isInteger(historyDays) || historyDays < 1 || historyDays > 365) {
      throw new Error("History days must be a whole number from 1 to 365.");
    }
    this._config = {
      title: "Renpho Scale",
      show_user_selector: true,
      show_view_selector: true,
      ...config,
      history_days: historyDays,
      metrics: [...metrics],
      trend_directions: { ...trendDirections },
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    if (!this._config || this._config.metrics.length === 0) {
      return 1;
    }
    return Math.max(
      2,
      Math.ceil(this._config.metrics.length / 2) + 1
        + (this._config.show_user_selector === false ? 0 : 1)
        + (this._config.show_view_selector === false ? 0 : 1),
    );
  }

  connectedCallback() {
    this._render();
  }

  _formatState(metric, stateObj) {
    if (!stateObj) {
      return { value: "Entity not found", unit: "" };
    }
    if (["unknown", "unavailable", "none"].includes(stateObj.state)) {
      return { value: "—", unit: "" };
    }
    if (metric.key === "last_measurement") {
      const date = new Date(stateObj.state);
      if (!Number.isNaN(date.getTime())) {
        return { value: date.toLocaleString(), unit: "" };
      }
    }
    return {
      value: stateObj.state,
      unit: stateObj.attributes.unit_of_measurement || "",
    };
  }

  _trend(metric, stateObj) {
    if (!stateObj || !metric.improvement) {
      return null;
    }
    const attributes = stateObj.attributes || {};
    const previousValue = attributes.previous_value;
    if (previousValue === undefined || previousValue === null || previousValue === "") {
      return null;
    }
    const current = Number(stateObj.state);
    const previous = Number(previousValue);
    if (!Number.isFinite(current) || !Number.isFinite(previous)) {
      return null;
    }
    const unit = attributes.unit_of_measurement || "";
    const previousText = `${previousValue} ${unit}`.trim();
    const difference = current - previous;
    let symbol = "→";
    let className = "neutral";
    let label = `No change from ${previousText}`;
    if (difference !== 0) {
      const direction = this._config.trend_directions[metric.key] || metric.improvement;
      const increased = difference > 0;
      const improved = increased === (direction === "up");
      symbol = increased ? "▲" : "▼";
      className = improved ? "good" : "bad";
      label = `${improved ? "Good" : "Bad"} progress: ${increased ? "up" : "down"} from ${previousText}`;
    }
    if (attributes.previous_measured_at) {
      const previousDate = new Date(attributes.previous_measured_at);
      if (!Number.isNaN(previousDate.getTime())) {
        label += ` on ${previousDate.toLocaleString()}`;
      }
    }
    return { symbol, className, label };
  }

  _renderUserSelector() {
    const container = this.shadowRoot.getElementById("user");
    container.replaceChildren();
    if (!this._hass || this._config.show_user_selector === false) {
      return;
    }
    const entityId = RenphoScaleCard.userEntityFor(this._config);
    const stateObj = this._hass.states[entityId];
    const options = stateObj && stateObj.attributes.options;
    if (!stateObj || !Array.isArray(options)) {
      return;
    }
    const label = document.createElement("label");
    label.className = "user-label";
    const caption = document.createElement("span");
    caption.textContent = "Measurement mode (Auto or forced user)";
    const select = document.createElement("select");
    select.className = "user-select";
    select.dataset.entityId = entityId;
    options.forEach((optionName) => {
      const option = document.createElement("option");
      option.value = optionName;
      option.textContent = optionName;
      select.append(option);
    });
    select.value = stateObj.state;
    select.disabled = ["unknown", "unavailable"].includes(stateObj.state);
    select.addEventListener("change", async () => {
      select.disabled = true;
      try {
        await this._hass.callService("select", "select_option", {
          entity_id: entityId,
          option: select.value,
        });
        this._userError = "";
      } catch (error) {
        this._userError = "Could not change user. Check the Home Assistant logs.";
        this._render();
      }
    });
    label.append(caption, select);
    container.replaceChildren(label);
  }

  _renderViewSelector() {
    const container = this.shadowRoot.getElementById("view");
    container.replaceChildren();
    if (!this._hass || this._config.show_view_selector === false) {
      return;
    }
    const entityId = RenphoScaleCard.viewEntityFor(this._config);
    const stateObj = this._hass.states[entityId];
    const options = stateObj && stateObj.attributes.options;
    if (!stateObj || !Array.isArray(options)) {
      return;
    }
    const label = document.createElement("label");
    label.className = "user-label";
    const caption = document.createElement("span");
    caption.textContent = "View measurement history for";
    const select = document.createElement("select");
    select.className = "user-select";
    select.dataset.entityId = entityId;
    options.forEach((optionName) => {
      const option = document.createElement("option");
      option.value = optionName;
      option.textContent = optionName;
      select.append(option);
    });
    select.value = stateObj.state;
    select.disabled = ["unknown", "unavailable"].includes(stateObj.state);
    select.addEventListener("change", async () => {
      select.disabled = true;
      try {
        await this._hass.callService("select", "select_option", {
          entity_id: entityId,
          option: select.value,
        });
        this._viewError = "";
      } catch (error) {
        this._viewError = "Could not change the viewed user. Check the Home Assistant logs.";
        this._render();
      }
    });
    label.append(caption, select);
    container.replaceChildren(label);
  }

  _renderProfileAndStatus(metricStates, viewState) {
    const profileElement = this.shadowRoot.getElementById("last-profile");
    const weightState = this._hass && this._hass.states[this._config.entity];
    const profile = weightState && weightState.attributes.profile;
    const viewing = viewState && viewState.state
      && !["unknown", "unavailable"].includes(viewState.state);
    profileElement.textContent = viewing
      ? `Viewing: ${viewState.state}`
      : (profile ? `Last measurement profile: ${profile}` : "");
    profileElement.hidden = !viewing && !profile;

    const status = this.shadowRoot.getElementById("status");
    status.textContent = "";
    status.hidden = true;
    if (!this._hass || metricStates.length === 0) {
      return;
    }
    let message = this._userError || this._viewError || "";
    let isError = Boolean(message);
    if (!message && weightState && weightState.attributes.identified === false) {
      const slot = weightState.attributes.user_index;
      message = `Latest measurement is unassigned (scale slot ${slot}); no person's history was changed.`;
    }
    if (!message) {
      const present = metricStates.filter((item) => item.stateObj);
      const hasValue = present.some((item) => (
        !["unknown", "unavailable", "none"].includes(item.stateObj.state)
      ));
      if (!hasValue) {
        message = present.length === 0
          ? "Scale entities not found. Check the weight sensor and entity prefixes in the card editor."
          : "Waiting for scale — wake it beside Home Assistant and step on.";
        isError = present.length === 0;
      }
    }
    status.textContent = message;
    status.hidden = !message;
    status.classList.toggle("error", isError);
  }

  _historyPath(entityId, now = new Date()) {
    const end = now;
    const start = new Date(end.getTime() - this._config.history_days * 86400000);
    const params = new URLSearchParams({
      entity_id: entityId,
      start_date: start.toISOString(),
      end_date: end.toISOString(),
      back: "1",
    });
    return `/history?${params.toString()}`;
  }

  _openHistory(entityId) {
    const path = this._historyPath(entityId);
    window.history.pushState(null, "", path);
    fireEvent(window, "location-changed", { replace: false });
  }

  _render() {
    if (!this.shadowRoot || !this._config) {
      return;
    }
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .title { font-size: 1.25rem; font-weight: 500; margin: 0 0 12px; }
        .user-label { display: grid; gap: 6px; margin: 0 0 12px; }
        .user-label > span, .last-profile { color: var(--secondary-text-color); font-size: 0.85rem; }
        .user-select {
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          color: var(--primary-text-color);
          font: inherit;
          padding: 9px;
          width: 100%;
        }
        .last-profile { margin: -4px 0 12px; }
        .status {
          background: var(--secondary-background-color);
          border-radius: 8px;
          color: var(--secondary-text-color);
          margin: 0 0 12px;
          padding: 10px;
        }
        .status.error { color: var(--error-color); }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));
          gap: 10px;
        }
        .metric {
          appearance: none;
          background: var(--secondary-background-color);
          border: 0;
          border-radius: 12px;
          color: var(--primary-text-color);
          cursor: pointer;
          font: inherit;
          min-height: 82px;
          padding: 12px;
          text-align: left;
        }
        .metric:hover { background: var(--divider-color); }
        .metric:focus-visible { outline: 2px solid var(--accent-color); }
        .label {
          color: var(--secondary-text-color);
          display: block;
          font-size: 0.85rem;
          margin-bottom: 8px;
        }
        .reading { align-items: baseline; display: flex; flex-wrap: wrap; gap: 5px; }
        .value { font-size: 1.35rem; font-weight: 500; overflow-wrap: anywhere; }
        .unit { color: var(--secondary-text-color); font-size: 0.9rem; }
        .trend { font-size: 0.85rem; font-weight: 700; line-height: 1; }
        .trend.good { color: var(--success-color, #2e7d32); }
        .trend.bad { color: var(--error-color, #c62828); }
        .trend.neutral { color: var(--secondary-text-color); }
        .empty { color: var(--secondary-text-color); padding: 12px 0; }
      </style>
      <ha-card>
        <div class="title" id="title"></div>
        <div id="user"></div>
        <div id="view"></div>
        <div class="last-profile" id="last-profile"></div>
        <div class="status" id="status"></div>
        <div class="grid" id="grid"></div>
      </ha-card>`;

    const title = this.shadowRoot.getElementById("title");
    title.textContent = this._config.title || "";
    title.hidden = !this._config.title;
    const viewState = this._config.show_view_selector === false || !this._hass
      ? null
      : this._hass.states[RenphoScaleCard.viewEntityFor(this._config)];
    const metricStates = this._config.metrics.map((key) => {
      const entityId = this.entityForView(key, viewState);
      return {
        key,
        stateObj: this._hass ? this._hass.states[entityId] : null,
      };
    });
    this._renderUserSelector();
    this._renderViewSelector();
    this._renderProfileAndStatus(metricStates, viewState);
    const grid = this.shadowRoot.getElementById("grid");

    if (this._config.metrics.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No values selected. Edit the card to choose measurements.";
      grid.replaceChildren(empty);
      return;
    }

    const tiles = metricStates.map(({ key, stateObj }) => {
      const metric = metricByKey(key);
      const entityId = this.entityForView(key, viewState);
      const reading = this._formatState(metric, stateObj);
      const trend = this._trend(metric, stateObj);
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "metric";
      tile.dataset.key = key;
      tile.setAttribute(
        "aria-label",
        `${metric.label}: ${reading.value} ${reading.unit}${trend ? `, ${trend.label}` : ""}`.trim(),
      );

      const label = document.createElement("span");
      label.className = "label";
      label.textContent = metric.label;
      const readingRow = document.createElement("span");
      readingRow.className = "reading";
      const value = document.createElement("span");
      value.className = "value";
      value.textContent = reading.value;
      const unit = document.createElement("span");
      unit.className = "unit";
      unit.textContent = reading.unit;
      readingRow.append(value, unit);
      if (trend) {
        const arrow = document.createElement("span");
        arrow.className = `trend ${trend.className}`;
        arrow.textContent = trend.symbol;
        arrow.title = trend.label;
        arrow.setAttribute("aria-hidden", "true");
        readingRow.append(arrow);
      }
      tile.append(label, readingRow);
      tile.addEventListener("click", () => this._openHistory(entityId));
      return tile;
    });
    grid.replaceChildren(...tiles);
  }
}

class RenphoScaleCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._form = null;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
    }
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (this._form) {
      this._form.data = this._formData();
      return;
    }
    this.shadowRoot.innerHTML = `
      <style>
        .hint { color: var(--secondary-text-color); font-size: 0.9rem; margin: 12px 0 0; }
      </style>
      <ha-form id="form"></ha-form>
      <p class="hint">Choose Auto or a forced measurement user, whose per-person values appear, and exactly which metrics are visible. Select a value to open its history.</p>`;
    this._form = this.shadowRoot.getElementById("form");
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "title", selector: { text: {} } },
      { name: "entity", required: true, selector: { entity: { domain: "sensor" } } },
      {
        name: "history_days",
        required: true,
        selector: {
          number: { min: 1, max: 365, step: 1, unit_of_measurement: "days", mode: "box" },
        },
      },
      { name: "user_entity", selector: { entity: { domain: "select" } } },
      { name: "show_user_selector", selector: { boolean: {} } },
      { name: "view_entity", selector: { entity: { domain: "select" } } },
      { name: "show_view_selector", selector: { boolean: {} } },
      {
        name: "metrics",
        required: true,
        selector: {
          select: {
            multiple: true,
            options: METRICS.map((metric) => ({ value: metric.key, label: metric.label })),
          },
        },
      },
    ];
    this._form.computeLabel = (schema) => ({
      title: "Card title",
      entity: "Weight sensor",
      history_days: "History range (days)",
      user_entity: "User selector entity (optional)",
      show_user_selector: "Show user selector",
      view_entity: "Viewed-user selector entity (optional)",
      show_view_selector: "Show viewed-user selector",
      metrics: "Values to display",
    })[schema.name] || schema.name;
    this._form.data = this._formData();
    this._form.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      this._config = { ...this._config, ...event.detail.value };
      fireEvent(this, "config-changed", { config: this._config });
    });
  }

  _formData() {
    return {
      title: this._config.title === undefined ? "Renpho Scale" : this._config.title,
      entity: this._config.entity || "sensor.renpho_r_msb01_weight",
      history_days: this._config.history_days === undefined ? 30 : this._config.history_days,
      user_entity: this._config.user_entity || "",
      show_user_selector: this._config.show_user_selector !== false,
      view_entity: this._config.view_entity || "",
      show_view_selector: this._config.show_view_selector !== false,
      metrics: this._config.metrics === undefined ? [...DEFAULT_METRICS] : this._config.metrics,
    };
  }
}

if (!customElements.get("renpho-rmsb01-card")) {
  customElements.define("renpho-rmsb01-card", RenphoScaleCard);
}
if (!customElements.get("renpho-rmsb01-card-editor")) {
  customElements.define("renpho-rmsb01-card-editor", RenphoScaleCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "renpho-rmsb01-card")) {
  window.customCards.push({
    type: "renpho-rmsb01-card",
    name: "Renpho Scale",
    description: "Selectable R-MSB01 weight and body-composition values",
    preview: true,
    documentationURL: "https://github.com/mallory303/renpho-rmsb01-home-assistant#renpho-scale-card",
  });
}
