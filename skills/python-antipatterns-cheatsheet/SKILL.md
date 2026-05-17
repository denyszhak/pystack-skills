---
name: python-antipatterns-cheatsheet
description: |
  Use when considering a Java/GoF-shaped pattern that agents commonly generate in
  Python: Singleton, Abstract Factory, or Factory Method. Use when reviewing code
  defining `class *Singleton`, `class Abstract*Factory`, `*Factory.create(...)`, or
  when the user asks "is X a good idea in Python?" Encodes: which imported
  patterns usually add ceremony in Python, what to use instead, and which positive
  skill has the detail.
  Do NOT use for: deep dives — this is the quick lookup. Each entry points to
  the positive skill with the full alternative.
---

# Anti-pattern cheatsheet

The GoF book was written for C++ and Java in 1994. Some of its patterns address language constraints those languages had (no first-class functions, no modules-as-namespaces, mandatory `new`) that Python doesn't. Agents still import those shapes into Python, usually as ceremony.

This is the quick reference for the imported patterns that show up in real Python reviews. It is not a GoF encyclopedia.

## The cheatsheet

### Singleton — anti-pattern

**Symptom:** `class Logger: _instance = None; def __new__(cls): if cls._instance is None: ...`; or `Logger.instance()` as the canonical accessor; or `@singleton` decorator.

**Why it fights Python:** Python has modules. A module is loaded once. A module-level variable IS a singleton. There's no `new` keyword to prevent — there's just construction, which you can choose not to do.

For services with app-lifetime state (DB pool, HTTP client), use dependency injection — create once in `lifespan`, store on `app.state`, inject through `Depends`. Singletons hide their dependencies; DI makes them explicit and testable.

**Use instead:**
- Module-level constants for true constants
- Dependency injection for services and pools (`python-fastapi-sa-app-setup`)

```python
# Don't
class StripeClient:
    _instance: "StripeClient | None" = None
    @classmethod
    def instance(cls) -> "StripeClient":
        if cls._instance is None:
            cls._instance = cls(...)
        return cls._instance

# Do — init in lifespan, inject via Depends
async def init_stripe_client(app: FastAPI, config: StripeConfig) -> None:
    app.state.stripe_client = StripeClient(...)

def get_stripe_client(request: Request) -> StripeClient:
    return request.app.state.stripe_client
```

See: `python-fastapi-sa-app-setup`, `python-external-client`

---

### Abstract Factory — anti-pattern

**Symptom:** `class AbstractEmailClientFactory: @abstractmethod def create(...)`; concrete factory subclasses for each "family" of products.

**Why it fights Python:** Classes are first-class objects — you can pass the class itself, or store classes in a dict, and the dispatch becomes a one-line lookup. No `AbstractFactory → ConcreteFactory → Product` hierarchy needed.

**Use instead:**
- Class registry (dict of name → class). The Pythonic shape for value-based dispatch.
- Match-case for tighter literal dispatch when the set is small and closed.
- A bare factory function only when there's no dispatch at all — just construction logic.

```python
# Don't — Java-shaped AbstractFactory + ConcreteFactory hierarchy
class AbstractEmailClientFactory(ABC):
    @abstractmethod
    def create_client(self, config: EmailConfig) -> EmailClient: ...

class SendGridClientFactory(AbstractEmailClientFactory):
    def create_client(self, config: EmailConfig) -> EmailClient:
        return SendGridClient(config)


# Do — dict dispatch. Classes ARE first-class objects in Python; store them.
_EMAIL_CLIENTS: dict[str, type[EmailClient]] = {
    "sendgrid": SendGridClient,
    "postmark": PostmarkClient,
    "ses":      SESClient,
}

def make_email_client(config: EmailConfig) -> EmailClient:
    try:
        return _EMAIL_CLIENTS[config.provider](config)
    except KeyError:
        raise ValueError(f"unknown email provider: {config.provider}")
```

Adding a new provider is one entry in the dict, not a new `if` branch.

For *closed* sets where you want exhaustiveness checking from `ty`, match-case also works:

```python
def make_email_client(config: EmailConfig) -> EmailClient:
    match config.provider:
        case "sendgrid": return SendGridClient(config)
        case "postmark": return PostmarkClient(config)
        case "ses":      return SESClient(config)
        case other:      raise ValueError(f"unknown email provider: {other}")
```

Use dict for open sets (plugin-style; consumers register their own). Use match for closed sets (fixed list). Avoid `if/elif` chains — they don't scale and aren't idiomatic.

See: `python-typing-idioms`, `python-fastapi-sa-app-setup`

---

### Factory Method — `@classmethod` returning `Self`

**Symptom:** Subclasses override a `_create()` method to choose what to construct.

**Why it fights Python:** Subclasses can override `__init__` directly, or you can use a `@classmethod` returning `Self` to allow per-subclass construction logic. Either way is simpler than the GoF subclass-dance.

**Use instead:**
- `@classmethod from_X(cls, ...) -> Self` for alternative constructors
- Subclass `__init__` overrides for variants

```python
class OrderGet(BaseModel):
    @classmethod
    def from_model(cls, order: Order) -> Self:
        return cls.model_validate(order)

    @classmethod
    def from_openai(cls, payload: dict) -> Self:
        return cls(id=..., customer_id=...)
```

See: `python-typing-idioms`, `python-service-and-schema-cohesion`

---

## When to break these rules

These verdicts assume Python. In a polyglot codebase that ports patterns from other languages, some of these can be the right call for consistency. The verdict here is "usually ceremony when starting fresh in Python."

A few specific exceptions:

- **Singleton** — if you genuinely need a class-level singleton (not an app-lifetime resource, but a thing whose identity matters), the `__new__` trick works. Almost always a smell, but not always wrong.
- **Factory Method** — if subclass construction behavior is genuinely part of a class hierarchy, use it. In ordinary app code, prefer `from_<source>` constructors or a plain factory function.

## See also

- `python-typing-idioms` — `Protocol`, `Self`, alternative constructors via classmethod
- `python-fastapi-sa-app-setup` — Singleton redirect (DI)
- `python-stdlib-idioms` — when GoF Composite or Iterator *is* the right shape (Protocol + dataclass for trees; generators for iteration)
