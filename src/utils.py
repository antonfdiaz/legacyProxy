import json
import sys
import subprocess

def update_config_file(config):
    with open("config.json","w") as f:
        json.dump({
            "general": config.general.__dict__,
            "services": config.services.__dict__,
        },f,indent=4)

def set_config_value(section,key,config):
    current_value = getattr(getattr(config,section),key)
    
    if isinstance(current_value, bool):
        new_value = not current_value
    else:
        title = f"Set {section}.{key}".replace('"','\\"')
        prompt = f"Current value: {current_value}\nEnter new value:".replace('"','\\"')
        default = str(current_value).replace('"','\\"')
        
        try:
            if sys.platform == "darwin":
                script = f'try\ntell application "System Events"\nactivate\nreturn text returned of (display dialog "{prompt}" default answer "{default}" with title "{title}")\nend tell\non error\nreturn ""\nend try'
                new_value = subprocess.run(["osascript","-e",script],capture_output=True,text=True).stdout.strip() or None
            elif sys.platform == "win32":
                script = f"Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.Interaction]::InputBox(\"{prompt}\", \"{title}\", \"{default}\")"
                new_value = subprocess.run(["powershell","-Command",script],capture_output=True,text=True,creationflags=0x08000000).stdout.strip() or None
            else:
                res = subprocess.run(["zenity","--entry",f"--title={title}",f"--text={prompt}",f"--entry-text={default}"],capture_output=True,text=True)
                new_value = res.stdout.strip() if res.returncode == 0 else None
        except Exception:
            return

        if not new_value: return
        
        if isinstance(current_value,int):
            try:
                new_value = int(new_value)
            except ValueError:
                return

    setattr(getattr(config,section),key,new_value)
    update_config_file(config)
    print(f"[INFO] updated {section}.{key} to {new_value}")