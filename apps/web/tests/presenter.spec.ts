import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
test('presenter can activate, inspect and reset a bounded scenario',async({page})=>{
 let scenario='healthy';
 await page.route('**/control/**',async route=>{
  const url=new URL(route.request().url());let body:unknown={};
  if(url.pathname==='/control/status')body={run_id:'run-fixture'};
  if(url.pathname==='/control/guard-probe')body={denied:true,action:'deny',source:'grafana',model_invoked:false,business_actions_executed:false,rule_id:'native-rule'};
  if(url.pathname.endsWith('/scenario')){scenario=route.request().method()==='DELETE'?'healthy':'supplier_injection';body={scenario,expires_at:new Date(Date.now()+300000).toISOString()};}
  if(url.pathname.endsWith('/evidence'))body={scenario,replacements_count:0,notifications_count:0};
  await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto('/presenter');await expect(page.getByText('run-fixture',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Activate scenario',exact:true}).click();await expect(page.getByText(/supplier_injection active/)).toBeVisible();
 await page.getByRole('button',{name:'Reset & verify',exact:true}).click();await expect(page.getByRole('button',{name:'Activate scenario',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'Run native guard check',exact:true}).click();await expect(page.getByText('Native guard denied the operator probe',{exact:true})).toBeVisible();await expect(page.getByText('Model invoked: false. Business actions executed: false.',{exact:true})).toBeVisible();
 const result=await new AxeBuilder({page}).analyze();expect(result.violations).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`test-results/presenter-${test.info().project.name}.png`,fullPage:true});
});
