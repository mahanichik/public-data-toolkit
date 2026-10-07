package main

import (
  "encoding/json"
  "flag"
  "fmt"
  "io"
  "net"
  "net/http"
  "net/url"
  "os"
  "sort"
  "time"

  wappalyzer "github.com/projectdiscovery/wappalyzergo"
)

func publicURL(raw string) (*url.URL,error) {
  u,err:=url.Parse(raw); if err!=nil || (u.Scheme!="http" && u.Scheme!="https") || u.Hostname()=="" || u.User!=nil { return nil,fmt.Errorf("invalid public URL") }
  ips,err:=net.LookupIP(u.Hostname()); if err!=nil { return nil,err }
  for _,ip:=range ips { if ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() { return nil,fmt.Errorf("non-public target rejected") } }
  return u,nil
}

func main() {
  raw:=flag.String("url","","public http/https URL"); flag.Parse()
  u,err:=publicURL(*raw); if err!=nil { fmt.Fprintln(os.Stderr,err); os.Exit(2) }
  client:=&http.Client{Timeout:20*time.Second,CheckRedirect:func(req *http.Request,via []*http.Request) error { _,e:=publicURL(req.URL.String()); return e }}
  req,_:=http.NewRequest("GET",u.String(),nil); req.Header.Set("User-Agent","PublicTechDetector/1")
  resp,err:=client.Do(req); if err!=nil { fmt.Fprintln(os.Stderr,err); os.Exit(1) }; defer resp.Body.Close()
  body,err:=io.ReadAll(io.LimitReader(resp.Body,4<<20)); if err!=nil { fmt.Fprintln(os.Stderr,err); os.Exit(1) }
  app,err:=wappalyzer.New(); if err!=nil { fmt.Fprintln(os.Stderr,err); os.Exit(1) }
  fp:=app.Fingerprint(resp.Header,body)
  tech:=make([]string,0,len(fp)); for k:=range fp { tech=append(tech,k) }; sort.Strings(tech)
  json.NewEncoder(os.Stdout).Encode(map[string]any{"url":u.String(),"status":resp.StatusCode,"technologies":tech})
}
