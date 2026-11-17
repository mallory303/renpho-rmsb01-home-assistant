import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(
  new URL("../custom_components/renpho_rmsb01/www/renpho-rmsb01-card.js", import.meta.url),
  "utf8",
);

class FakeElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.classList = { toggle: () => {} };
    this.textContent = "";
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  addEventListener(type, callback) {
    this.listeners[type] = callback;
  }
}

class FakeShadowRoot {
  constructor() {
    this.elements = new Map();
  }

  getElementById(id) {
    if (!this.elements.has(id)) {
      this.elements.set(id, new FakeElement());
    }
    return this.elements.get(id);
  }
}

function loadCard() {
  const definitions = new Map();
  const sandbox = {
    window: { customCards: [] },
    customElements: {
      define: (name, constructor) => definitions.set(name, constructor),
      get: (name) => definitions.get(name),
    },
    HTMLElement: class {
      attachShadow() {
        this.shadowRoot = {};
        return this.shadowRoot;
      }
    },
    CustomEvent: class {},
    document: { createElement: () => new FakeElement() },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(`{\n${source}\n}`, sandbox);
  return { sandbox, Card: definitions.get("renpho-rmsb01-card") };
}

const { sandbox, Card } = loadCard();
const renderCard = Card.prototype._render;
Card.prototype._render = () => {};

test("all fourteen values have unique keys and suffixes", () => {
  const metrics = Card.availableMetrics;
  assert.equal(metrics.length, 14);
  assert.equal(new Set(metrics.map((metric) => metric.key)).size, 14);
  assert.equal(new Set(metrics.map((metric) => metric.suffix)).size, 14);
  assert.deepEqual(
    Array.from(metrics, (metric) => metric.key),
    [
      "weight", "bmi", "body_fat", "subcutaneous_fat", "visceral_fat",
      "body_water", "muscle_percentage", "bone_mass", "basal_metabolic_rate",
      "protein", "lean_body_mass", "muscle_mass", "body_age", "last_measurement",
    ],
  );
  metrics.slice(0, -1).forEach((metric) => {
    assert.ok(["up", "down"].includes(metric.improvement), `${metric.key} has a trend direction`);
  });
  assert.equal(metrics.at(-1).improvement, null);
});

test("selected values derive the installed entity IDs from the weight sensor", () => {
  const config = { entity: "sensor.renpho_r_msb01_weight" };
  assert.equal(Card.entityFor(config, "weight"), "sensor.renpho_r_msb01_weight");
  assert.equal(Card.entityFor(config, "body_fat"), "sensor.renpho_r_msb01_body_fat");
  assert.equal(Card.entityFor(config, "muscle_percentage"), "sensor.renpho_r_msb01_muscle_percentage");
  assert.equal(Card.entityFor(config, "basal_metabolic_rate"), "sensor.renpho_r_msb01_basal_metabolic_rate");
  assert.equal(Card.entityFor(config, "last_measurement"), "sensor.renpho_r_msb01_last_measurement");
});

test("per-metric entity overrides support renamed entities", () => {
  const config = {
    entity: "sensor.my_scale_weight",
    entities: { body_fat: "sensor.custom_fat", bmi: "sensor.custom_bmi" },
  };
  assert.equal(Card.entityFor(config, "body_fat"), "sensor.custom_fat");
  assert.equal(Card.entityFor(config, "bmi"), "sensor.custom_bmi");
  assert.equal(Card.entityFor(config, "body_water"), "sensor.my_scale_body_water");
});

test("card picker discovers the installed scale and selects useful defaults", () => {
  const config = Card.getStubConfig({
    states: {
      "sensor.renpho_r_msb01_weight": { state: "unavailable" },
      "sensor.other_weight": { state: "1" },
    },
  });
  assert.equal(config.entity, "sensor.renpho_r_msb01_weight");
  assert.equal(config.type, "custom:renpho-rmsb01-card");
  assert.equal(config.metrics.length, 8);
  assert.ok(config.metrics.includes("weight"));
  assert.ok(config.metrics.includes("last_measurement"));
});

test("configuration validates entity and metric names but permits an empty selection", () => {
  const card = new Card();
  assert.throws(() => card.setConfig({ entity: "sensor.weight", metrics: ["not_real"] }));
  assert.throws(() => card.setConfig({ metrics: ["weight"] }));
  card.setConfig({ entity: "sensor.renpho_r_msb01_weight", metrics: [] });
  assert.equal(card.getCardSize(), 1);
  card.setConfig({ entity: "sensor.renpho_r_msb01_weight", metrics: ["weight", "bmi"] });
  assert.deepEqual([...card._config.metrics], ["weight", "bmi"]);
  assert.throws(() => card.setConfig({
    entity: "sensor.renpho_r_msb01_weight", trend_directions: { weight: "sideways" },
  }));
  assert.throws(() => card.setConfig({
    entity: "sensor.renpho_r_msb01_weight", trend_directions: { unknown: "up" },
  }));
});

test("numeric tiles color progress and keep unchanged or incomplete values neutral", () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({
    entity: "sensor.renpho_r_msb01_weight",
    metrics: ["weight", "body_water", "body_fat", "bone_mass", "body_age", "last_measurement"],
  });
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": {
        state: "69.50", attributes: { unit_of_measurement: "kg", previous_value: 70.0 },
      },
      "sensor.renpho_r_msb01_body_water": {
        state: "55.0", attributes: { unit_of_measurement: "%", previous_value: 54.0 },
      },
      "sensor.renpho_r_msb01_body_fat": {
        state: "23.0", attributes: { unit_of_measurement: "%", previous_value: 22.0 },
      },
      "sensor.renpho_r_msb01_bone_mass": {
        state: "3.00", attributes: { unit_of_measurement: "kg", previous_value: 3.0 },
      },
      "sensor.renpho_r_msb01_body_age": {
        state: "unavailable", attributes: { unit_of_measurement: "years", previous_value: 40 },
      },
      "sensor.renpho_r_msb01_last_measurement": {
        state: "2026-01-02T00:00:00+00:00",
        attributes: { previous_value: "2026-01-01T00:00:00+00:00" },
      },
    },
  };
  renderCard.call(card);
  const tiles = card.shadowRoot.getElementById("grid").children;
  const arrows = tiles.map((tile) => tile.children[1].children[2]);
  assert.equal(arrows[0].textContent, "▼");
  assert.equal(arrows[0].className, "trend good");
  assert.match(arrows[0].title, /^Good progress: down from 70 kg/);
  assert.equal(arrows[1].textContent, "▲");
  assert.equal(arrows[1].className, "trend good");
  assert.equal(arrows[2].textContent, "▲");
  assert.equal(arrows[2].className, "trend bad");
  assert.match(arrows[2].title, /^Bad progress: up from 22 %/);
  assert.equal(arrows[3].textContent, "→");
  assert.equal(arrows[3].className, "trend neutral");
  assert.equal(arrows[4], undefined);
  assert.equal(arrows[5], undefined);
  assert.match(tiles[0].attributes["aria-label"], /Good progress/);
});

test("trend direction overrides support personal goals", () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({
    entity: "sensor.renpho_r_msb01_weight",
    metrics: ["weight"],
    trend_directions: { weight: "up" },
  });
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": {
        state: "71.0", attributes: { unit_of_measurement: "kg", previous_value: 70.0 },
      },
    },
  };
  renderCard.call(card);
  const arrow = card.shadowRoot.getElementById("grid").children[0].children[1].children[2];
  assert.equal(arrow.textContent, "▲");
  assert.equal(arrow.className, "trend good");
});

test("rendering shows only selected values and preserves unavailable states", () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({
    title: "Synthetic scale",
    entity: "sensor.renpho_r_msb01_weight",
    metrics: ["weight", "body_fat", "body_water"],
  });
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": { state: "70.00", attributes: { unit_of_measurement: "kg" } },
      "sensor.renpho_r_msb01_body_fat": { state: "22.3", attributes: { unit_of_measurement: "%" } },
      "sensor.renpho_r_msb01_body_water": { state: "unavailable", attributes: { unit_of_measurement: "%" } },
      "sensor.renpho_r_msb01_bmi": { state: "22.1", attributes: { unit_of_measurement: "kg/m²" } },
    },
  };
  renderCard.call(card);
  const tiles = card.shadowRoot.getElementById("grid").children;
  assert.deepEqual(Array.from(tiles, (tile) => tile.dataset.key), ["weight", "body_fat", "body_water"]);
  assert.equal(tiles[0].children[1].children[0].textContent, "70.00");
  assert.equal(tiles[1].children[1].children[0].textContent, "22.3");
  assert.equal(tiles[2].children[1].children[0].textContent, "—");
  assert.ok(!tiles.some((tile) => tile.dataset.key === "bmi"));
});

test("user selector derives its entity and calls select_option", async () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({
    entity: "sensor.renpho_r_msb01_weight",
    metrics: ["weight"],
  });
  assert.equal(
    Card.userEntityFor(card._config),
    "select.renpho_r_msb01_user",
  );
  assert.equal(
    Card.userEntityFor({ ...card._config, user_entity: "select.custom_user" }),
    "select.custom_user",
  );
  const calls = [];
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": {
        state: "70.00",
        attributes: { unit_of_measurement: "kg", profile: "User A" },
      },
      "select.renpho_r_msb01_user": {
        state: "User A",
        attributes: { options: ["User A", "User B"] },
      },
    },
    callService: async (...args) => calls.push(args),
  };
  renderCard.call(card);
  const label = card.shadowRoot.getElementById("user").children[0];
  const selector = label.children[1];
  assert.equal(selector.children.length, 2);
  assert.equal(selector.value, "User A");
  assert.equal(
    card.shadowRoot.getElementById("last-profile").textContent,
    "Last measurement profile: User A",
  );
  selector.value = "User B";
  await selector.listeners.change();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "select");
  assert.equal(calls[0][1], "select_option");
  assert.equal(calls[0][2].entity_id, "select.renpho_r_msb01_user");
  assert.equal(calls[0][2].option, "User B");
});

test("connection status distinguishes waiting from missing entities", () => {
  const waiting = new Card();
  waiting.shadowRoot = new FakeShadowRoot();
  waiting.setConfig({ entity: "sensor.renpho_r_msb01_weight", metrics: ["weight"] });
  waiting._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": { state: "unavailable", attributes: {} },
    },
  };
  renderCard.call(waiting);
  const waitingStatus = waiting.shadowRoot.getElementById("status");
  assert.equal(waitingStatus.hidden, false);
  assert.match(waitingStatus.textContent, /^Waiting for scale/);

  const missing = new Card();
  missing.shadowRoot = new FakeShadowRoot();
  missing.setConfig({ entity: "sensor.missing_weight", metrics: ["weight"] });
  missing._hass = { states: {} };
  renderCard.call(missing);
  const missingStatus = missing.shadowRoot.getElementById("status");
  assert.equal(missingStatus.hidden, false);
  assert.match(missingStatus.textContent, /^Scale entities not found/);
});

test("viewed-user selector switches to per-person entities without changing measurement mode", async () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({
    entity: "sensor.renpho_r_msb01_weight",
    metrics: ["weight", "body_fat"],
  });
  const calls = [];
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": {
        state: "70.00", attributes: { unit_of_measurement: "kg", profile: "User A" },
      },
      "sensor.user_a_weight": { state: "70.00", attributes: { unit_of_measurement: "kg" } },
      "sensor.user_a_body_fat": { state: "22.0", attributes: { unit_of_measurement: "%" } },
      "sensor.user_b_weight": { state: "80.00", attributes: { unit_of_measurement: "kg" } },
      "sensor.user_b_body_fat": { state: "30.0", attributes: { unit_of_measurement: "%" } },
      "select.renpho_r_msb01_user": {
        state: "Auto", attributes: { options: ["Auto", "User A", "User B"] },
      },
      "select.renpho_r_msb01_viewed_user": {
        state: "User B",
        attributes: {
          options: ["User A", "User B"],
          profile_entities: {
            "User A": { weight: "sensor.user_a_weight", body_fat: "sensor.user_a_body_fat" },
            "User B": { weight: "sensor.user_b_weight", body_fat: "sensor.user_b_body_fat" },
          },
        },
      },
    },
    callService: async (...args) => calls.push(args),
  };
  assert.equal(Card.viewEntityFor(card._config), "select.renpho_r_msb01_viewed_user");
  renderCard.call(card);
  const tiles = card.shadowRoot.getElementById("grid").children;
  assert.equal(tiles[0].children[1].children[0].textContent, "80.00");
  assert.equal(tiles[1].children[1].children[0].textContent, "30.0");
  assert.equal(card.shadowRoot.getElementById("last-profile").textContent, "Viewing: User B");
  const selector = card.shadowRoot.getElementById("view").children[0].children[1];
  selector.value = "User A";
  await selector.listeners.change();
  assert.equal(calls[0][2].entity_id, "select.renpho_r_msb01_viewed_user");
  assert.equal(calls[0][2].option, "User A");
});

test("unassigned native measurement does not masquerade as a family member", () => {
  const card = new Card();
  card.shadowRoot = new FakeShadowRoot();
  card.setConfig({ entity: "sensor.renpho_r_msb01_weight", metrics: ["weight"] });
  card._hass = {
    states: {
      "sensor.renpho_r_msb01_weight": {
        state: "65.0",
        attributes: { identified: false, user_index: 0, profile: null },
      },
    },
  };
  renderCard.call(card);
  const status = card.shadowRoot.getElementById("status");
  assert.match(status.textContent, /unassigned \(scale slot 0\)/);
  assert.match(status.textContent, /no person's history was changed/);
});

test("loading the resource twice does not duplicate definitions or picker entries", () => {
  vm.runInContext(`{\n${source}\n}`, sandbox);
  assert.equal(sandbox.window.customCards.length, 1);
  assert.equal(sandbox.window.customCards[0].type, "renpho-rmsb01-card");
});
