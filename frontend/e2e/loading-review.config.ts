import { defineConfig } from '@playwright/test';
process.env.LOADING_REVIEW_FIXTURE = 'true';
export default defineConfig({testDir:'.',testMatch:'loading-browser.spec.ts',timeout:90000,retries:0,workers:1,reporter:'list',use:{browserName:'chromium',headless:true,viewport:{width:1365,height:900}}});

