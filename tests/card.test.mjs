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

  addEventListener() {}
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

test("loading the resource twice does not duplicate definitions or picker entries", () => {
  vm.runInContext(`{\n${source}\n}`, sandbox);
  assert.equal(sandbox.window.customCards.length, 1);
  assert.equal(sandbox.window.customCards[0].type, "renpho-rmsb01-card");
});
