import requests
import json
import time

import secrets
import string

class ReolinkAPI:

    # Initialization function
    def __init__(self):
        # http post headers
        self.headers = { "Content-Type" : "application/json" }
    
    # Post data by requests.post
    def _postData(self,url,data):
        response = requests.post(url=url,headers=self.headers,data=json.dumps(data))
        return True if response.status_code==200 else False
    
    # Post data by requests.post and get result in forms of Json
    def _PostDataAndGetResult(self,url,data):
        response = requests.post(url=url,headers=self.headers,data=json.dumps(data))
        result = json.loads(response.text)
        return result[0]
    
    # Generate 16-length random character
    def _generateRandomCharacter(self,length=16) -> str:
        characters = string.ascii_letters + string.digits + '_'
        return ''.join(secrets.choice(characters) for _ in range(length))
        

    # ==== Log in
    def _apiLogin(self,ip_address,username,password):
        url = f'http://{ip_address}/api.cgi?cmd=Login'
        data = [{ "cmd":"Login", "param":{ "User":{ "Version": "0", "userName":f"{username}", "password":f"{password}"}}}]
        result = self._PostDataAndGetResult(url,data)
        token = result['value']['Token']['name']
        return token
    
    # ==== Log out
    def _apiLogout(self,ip_address,token):
        url = f'http://{ip_address}/api.cgi?cmd=Logout&token={token}'
        data = [{"cmd":"Logout","param":{}}]
        return self._postData(url,data)
    
    # ==== Set IR light on
    def _apiSetIRLightOn(self,ip_address,token):
        url = f'http://{ip_address}/api.cgi?cmd=SetIrLights&token={token}'
        data = [{"cmd":"SetIrLights","action":0,"param":{"IrLights": {"channel" : 0,"state":"On"}}}]
        return self._postData(url,data)
    
    # ==== Set IR light off
    def _apiSetIRLightOff(self,ip_address,token):
        url = f'http://{ip_address}/api.cgi?cmd=SetIrLights&token={token}'
        data = [{"cmd":"SetIrLights","action":0,"param":{"IrLights": {"channel" : 0,"state":"Off"}}}]
        return self._postData(url,data)
        
    # ==== Set white led on
    def _apiSetWhiteLedOn(self,ip_address,token):
        url = f'http://{ip_address}/api.cgi?cmd=SetWhiteLed&token={token}'
        data = [{"cmd":"SetWhiteLed","param":{"WhiteLed": {"channel" : 0,"state":1}}}]
        return self._postData(url,data)
    
    # ==== Set white led off
    def _apiSetWhiteLedOff(self,ip_address,token):
        url = f'http://{ip_address}/api.cgi?cmd=SetWhiteLed&token={token}'
        data = [{"cmd":"SetWhiteLed","param":{"WhiteLed": {"channel" : 0,"state":0}}}]
        return self._postData(url,data)
    

    # ==== Get snapshot
    def _apiGetSnap(self,ip_address,token):
        rs = self._generateRandomCharacter()
        url = f'http://{ip_address}/cgi-bin/api.cgi?cmd=Snap&channel=0&rs={rs}&token={token}'
        response = requests.post(url=url, headers=self.headers)
        content_type = response.headers.get('Content-type')
        if 'image' in content_type:
            return response.content
        elif 'application/json' in content_type:
            return None
        else:
            return None
    def _saveFrame(self,filepath,contents):
        with open(filepath, 'wb') as f:
            f.write(contents)
            
    # ==== Get Enc
    def _apiGetEnc(self,ip_address,token):
        url = f'http://{ip_address}/cgi-bin/api.cgi?cmd=GetEnc&token={token}'
        data = [{"cmd":"GetEnc","action":1,"param":{"channel": 0}}]
        result = self._PostDataAndGetResult(url,data)
        print(result)

    def run(self,ip_address,username,password):
        token = self._apiLogin(ip_address,username,password)
        print('LOGIN')

        flag = self._apiSetWhiteLedOn(ip_address,token)
        print(f'LED ON : {flag}')
        time.sleep(2)

        try:
            contents = self._apiGetSnap(ip_address,token)
            self._saveFrame(f'./test_{ip_address}.jpg',contents)
            print('IMAGE')
            # print(contents)
            # print(type(contents))
        except Exception as e:
            print(e)
        time.sleep(0.1)

        flag = self._apiSetWhiteLedOff(ip_address,token)
        print(f'LED OFF : {flag}')

        flag = self._apiLogout(ip_address,token)
        print(f'LOGOUT: {flag}')
    
    def runASD(self,ip_address,username,password):
        token = self._apiLogin(ip_address,username,password)
        print('LOGIN')
        self._apiGetEnc(ip_address,token)
        flag = self._apiLogout(ip_address,token)
        print(f'LOGOUT: {flag}')



# if __name__=='__main__':
#     username = 'admin'
#     password = 'asiadmin!'
#     r = ReolinkAPI()
#     # for k in range(10):
#     #     ip_address = f'192.168.99.{k+201}'
#     #     print(ip_address)
#     #     r.run(ip_address,username,password)

#     ip_address = '192.168.1.4'
#     # r.runASD(ip_address,username,password)
#     r.run(ip_address,username,password)
    