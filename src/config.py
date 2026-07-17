import json
import os
from dataclasses import dataclass

@dataclass
class GeneralConfig:
    host: str
    port: int
    chrome_headless: bool
    chrome_path: str
    
@dataclass
class ServicesConfig:
    google: bool
    reddit: bool
    wikipedia: bool
    github: bool

class Config:
    def __init__(self):
        config = self.load_config()
        general_config = config.get("general",{})
        services_config = config.get("services",{})
        
        self.general = GeneralConfig(
            host=general_config.get("host","0.0.0.0"),
            port=general_config.get("port",8080),
            chrome_headless=general_config.get("chrome_headless",True),
            chrome_path=general_config.get("chrome_path","/Applications/Google Chrome.app")
        )

        self.services = ServicesConfig(
            google=services_config.get("google",True),
            reddit=services_config.get("reddit",True),
            wikipedia=services_config.get("wikipedia",True),
            github=services_config.get("github",True)
        )

    def load_config(self):
        if not os.path.exists("config.json"):
            config = self.init_config()
            with open("config.json","w") as f:
                json.dump(config,f,indent=4)
        else:
            with open("config.json","r") as f:
                config = json.load(f)
        return config

    def init_config(self):
        default_config = {
            "general": {
                "host": "0.0.0.0",
                "port": 8080,
                "chrome_headless": True,
                "chrome_path": "/Applications/Google Chrome.app"
            },
            "services": {
                "google": True,
                "reddit": True,
                "wikipedia": True,
                "github": True,
            }
        }
        return default_config