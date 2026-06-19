DOMAIN = "philips_airplus_cloud"

CONF_TOKEN = "token"

CLIENT_ID = "-XsK7O6iEkLml77yDGDUi0ku"
CLIENT_SECRET = "V34BlAhuilIdOx0Imo16rGQ2"
REDIRECT_URI = "com.philips.air://loginredirect"
OIDC_BASE = "https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA"
AUTH_URL = f"{OIDC_BASE}/authorize"
TOKEN_URL = f"{OIDC_BASE}/oauth/token"
DA_BASE = "https://prod.eu-da.iot.versuni.com/api/da"
MQTT_HOST = "ats.prod.eu-da.iot.versuni.com"
MQTT_URL = f"wss://{MQTT_HOST}:443/mqtt"
TENANT = "da"

SCOPE = (
    "openid email profile address DI.Account.read DI.Account.write "
    "DI.AccountProfile.read DI.AccountProfile.write "
    "DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write "
    "DI.GeneralConsent.read subscriptions profile_extended consents "
    "DI.AccountSubscription.read DI.AccountSubscription.write"
)

PLATFORMS = ["sensor", "switch"]
