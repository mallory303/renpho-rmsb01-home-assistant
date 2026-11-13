const METRICS = [
  { key: "weight", label: "Weight", suffix: "weight" },
  { key: "bmi", label: "BMI", suffix: "bmi" },
  { key: "body_fat", label: "Body fat", suffix: "body_fat" },
  { key: "subcutaneous_fat", label: "Subcutaneous fat", suffix: "subcutaneous_fat" },
  { key: "visceral_fat", label: "Visceral fat", suffix: "visceral_fat" },
  { key: "body_water", label: "Body water", suffix: "body_water" },
  { key: "muscle_percentage", label: "Muscle percentage", suffix: "muscle_percentage" },
  { key: "bone_mass", label: "Bone mass", suffix: "bone_mass" },
  { key: "basal_metabolic_rate", label: "Basal metabolic rate", suffix: "basal_metabolic_rate" },
  { key: "protein", label: "Protein", suffix: "protein" },
  { key: "lean_body_mass", label: "Lean body mass", suffix: "lean_body_mass" },
  { key: "muscle_mass", label: "Muscle mass", suffix: "muscle_mass" },
  { key: "body_age", label: "Body age", suffix: "body_age" },
  { key: "last_measurement", label: "Last measurement", suffix: "last_measurement" },
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

  setConfig(config) {
    if (!config || typeof config.entity !== "string" || !config.entity.startsWith("sensor.")) {
      throw new Error("Select the scale's weight sensor entity.");
    }
    const metrics = config.metrics === undefined ? DEFAULT_METRICS : config.metrics;
    if (!Array.isArray(metrics) || metrics.some((key) => !metricByKey(key))) {
      throw new Error("The metrics list contains an unknown value.");
    }
    this._config = {
      title: "Renpho Scale",
      show_user_selector: true,
      ...config,
      metrics: [...metrics],
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
        + (this._config.show_user_selector === false ? 0 : 1),
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
    caption.textContent = "User for next measurement";
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

  _renderProfileAndStatus(metricStates) {
    const profileElement = this.shadowRoot.getElementById("last-profile");
    const weightState = this._hass && this._hass.states[this._config.entity];
    const profile = weightState && weightState.attributes.profile;
    profileElement.textContent = profile ? `Last measurement profile: ${profile}` : "";
    profileElement.hidden = !profile;

    const status = this.shadowRoot.getElementById("status");
    status.textContent = "";
    status.hidden = true;
    if (!this._hass || metricStates.length === 0) {
      return;
    }
    let message = this._userError || "";
    let isError = Boolean(this._userError);
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
        .empty { color: var(--secondary-text-color); padding: 12px 0; }
      </style>
      <ha-card>
        <div class="title" id="title"></div>
        <div id="user"></div>
        <div class="last-profile" id="last-profile"></div>
        <div class="status" id="status"></div>
        <div class="grid" id="grid"></div>
      </ha-card>`;

    const title = this.shadowRoot.getElementById("title");
    title.textContent = this._config.title || "";
    title.hidden = !this._config.title;
    const metricStates = this._config.metrics.map((key) => {
      const entityId = RenphoScaleCard.entityFor(this._config, key);
      return {
        key,
        stateObj: this._hass ? this._hass.states[entityId] : null,
      };
    });
    this._renderUserSelector();
    this._renderProfileAndStatus(metricStates);
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
      const entityId = RenphoScaleCard.entityFor(this._config, key);
      const reading = this._formatState(metric, stateObj);
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "metric";
      tile.dataset.key = key;
      tile.setAttribute("aria-label", `${metric.label}: ${reading.value} ${reading.unit}`.trim());

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
      tile.append(label, readingRow);
      tile.addEventListener("click", () => fireEvent(this, "hass-more-info", { entityId }));
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
      <p class="hint">Choose the next-measurement user and exactly which values appear. Select a value on the card to open its history.</p>`;
    this._form = this.shadowRoot.getElementById("form");
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "title", selector: { text: {} } },
      { name: "entity", required: true, selector: { entity: { domain: "sensor" } } },
      { name: "user_entity", selector: { entity: { domain: "select" } } },
      { name: "show_user_selector", selector: { boolean: {} } },
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
      user_entity: "User selector entity (optional)",
      show_user_selector: "Show user selector",
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
      user_entity: this._config.user_entity || "",
      show_user_selector: this._config.show_user_selector !== false,
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
